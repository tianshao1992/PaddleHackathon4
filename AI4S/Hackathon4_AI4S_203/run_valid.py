# -*- coding: utf-8 -*-


import os, sys, random, math
import numpy as np
import paddle
import paddle.nn as nn
from paddle.io import DataLoader
import read_data
from read_data import TurbDataset, ValiDataset
from Unet_model import UNet2d
from FNO_model import FNO2d
from Trans_model import FourierTransformer2D
import utils
from utils import log
from matplotlib import cm

dropout = 0.0
prop = [10000, 1.0, 0, 0.0]
net = 'UNet'
expo = 6
# statistics number
sta_number = 8

##########################
for p in (400, 3200, 25600):  # for Transformer and FNO
    # for p in (400, 800, 1600, 3200, 6400, 12800, 25600, 51200):   #for fig.11
    # for p in ((100, 200, 400, 1600, 3200, 6400, 12800)):  #for fig.10
    prop[0] = p

    data_path = os.path.join('data')
    train_path = os.path.join(data_path, 'train/')
    valid_path = os.path.join(data_path, 'test/')

    data = read_data.TurbDataset(prop, shuffle=1, dataDir=train_path, dataDirTest=valid_path)
    dataValidation = ValiDataset(data)
    validLoader = DataLoader(dataValidation, batch_size=1, shuffle=False, drop_last=True)
    print("Validation batches: {}".format(len(validLoader)))

    dataset = TurbDataset(prop, mode=TurbDataset.TEST, dataDir=train_path, dataDirTest=valid_path)
    # dataset = TurbDataset(None, mode=TurbDataset.TEST, dataDirTest="../data/test/")
    testLoader = DataLoader(dataset, batch_size=1, shuffle=False)

    if 'UNet' in net:
        net_model = UNet2d(channelExponent=expo, dropout=dropout)
    elif 'FNO' in net:
        net_model = FNO2d(in_dim=3, out_dim=3, modes=(32, 32), width=32, depth=4, steps=1, padding=4, activation='gelu')
    elif 'Transformer' in net:
        import yaml

        with open(os.path.join('transformer_config.yml')) as f:
            config = yaml.full_load(f)
        config = config['Transformer']
        net_model = FourierTransformer2D(**config)

    # loop over different trained models
    avgLoss = 0.
    losses = []
    models = []

    for s in range(sta_number):
        work_path = os.path.join('work', net, "prop-" + str(prop), "expo-" + str(expo), "statistics-" + str(s + 1))

        prefix = work_path + "/"
        utils.makeDirs([prefix])
        print("Output prefix: {}".format(prefix))

        lf = os.path.join('work', net, "prop-" + str(prop), "expo-" + str(expo)) + "/testout.txt"
        utils.makeDirs([prefix + "results_test"])
        utils.resetLog(lf)

        modelFn = prefix + "net_model"
        if not os.path.isfile(modelFn):
            continue

        models.append(modelFn)
        log(lf, "Loading " + modelFn)
        net_model.set_state_dict(paddle.load(modelFn))
        log(lf, "Loaded " + modelFn)
        # netG.cuda()

        criterionL1 = nn.L1Loss()
        # criterionL1.cuda()
        L1val_accum = 0.0
        L1val_dn_accum = 0.0
        lossPer_p_accum = 0
        lossPer_v_accum = 0
        lossPer_accum = 0

        net_model.eval()

        for i, data in enumerate(testLoader, 0):
            inputs, targets = data
            with paddle.no_grad():
                outputs = net_model(inputs)
            outputs = outputs[0]
            targets = targets[0]

            lossL1 = criterionL1(outputs, targets)
            L1val_accum += lossL1.item()

            outputs = np.array(outputs)
            targets = np.array(targets)

            # precentage loss by ratio of means which is same as the ratio of the sum
            lossPer_p = np.sum(np.abs(outputs[0] - targets[0])) / np.sum(np.abs(targets[0]))
            lossPer_v = (np.sum(np.abs(outputs[1] - targets[1])) + np.sum(np.abs(outputs[2] - targets[2]))) \
                        / (np.sum(np.abs(targets[1])) + np.sum(np.abs(targets[2])))
            lossPer = np.sum(np.abs(outputs - targets)) / np.sum(np.abs(targets))
            lossPer_p_accum += lossPer_p.item()
            lossPer_v_accum += lossPer_v.item()
            lossPer_accum += lossPer.item()

            log(lf, "Test sample %d" % i)
            log(lf, "    pressure:  abs. difference, ratio: %f , %f " % (np.sum(np.abs(outputs[0] - targets[0])),
                                                                         lossPer_p.item()))
            log(lf, "    velocity:  abs. difference, ratio: %f , %f " % (np.sum(np.abs(outputs[1] - targets[1])) +
                                                                         np.sum(np.abs(outputs[2] - targets[2])),
                                                                         lossPer_v.item()))
            log(lf, "    aggregate: abs. difference, ratio: %f , %f " % (np.sum(np.abs(outputs - targets)),
                                                                         lossPer.item()))

            # Calculate the norm
            input_ndarray = inputs.numpy()[0]
            v_norm = (np.max(np.abs(input_ndarray[0, :, :])) ** 2 + np.max(np.abs(input_ndarray[1, :, :])) ** 2) ** 0.5

            outputs_denormalized = dataset.denormalize(outputs, v_norm)
            targets_denormalized = dataset.denormalize(targets, v_norm)

            # denormalized error
            outputs_denormalized_comp = np.array([outputs_denormalized])
            # outputs_denormalized_comp=torch.from_numpy(outputs_denormalized_comp)
            targets_denormalized_comp = np.array([targets_denormalized])
            # targets_denormalized_comp=torch.from_numpy(targets_denormalized_comp)

            # targets_denormalized_comp, outputs_denormalized_comp = targets_denormalized_comp.float().cuda(), outputs_denormalized_comp.float().cuda()

            # outputs_dn.data.resize_as_(outputs_denormalized_comp).copy_(outputs_denormalized_comp)
            # targets_dn.data.resize_as_(targets_denormalized_comp).copy_(targets_denormalized_comp)

            outputs_dn = paddle.to_tensor(outputs_denormalized_comp)
            targets_dn = paddle.to_tensor(targets_denormalized_comp)

            lossL1_dn = criterionL1(outputs_dn, targets_dn)
            L1val_dn_accum += lossL1_dn.item()

            # write output image, note - this is currently overwritten for multiple models
            utils.imageOut(prefix + "results_test/" + "%04d" % (i), outputs, targets, normalize=False,
                           saveMontage=True, cmap=cm.RdBu_r)  # write normalized with error

        log(lf, "\n")
        L1val_accum /= len(testLoader)
        lossPer_p_accum /= len(testLoader)
        lossPer_v_accum /= len(testLoader)
        lossPer_accum /= len(testLoader)
        L1val_dn_accum /= len(testLoader)
        log(lf, "Loss percentage (p, v, combined): %f %%    %f %%    %f %% " %
            (lossPer_p_accum * 100, lossPer_v_accum * 100, lossPer_accum * 100))
        log(lf, "L1 error: %f" % (L1val_accum))
        log(lf, "Denormalized error: %f" % (L1val_dn_accum))
        log(lf, "\n")

        avgLoss += lossPer_accum
        losses.append(lossPer_accum)

    if len(losses) > 1:
        avgLoss /= len(losses)
        lossStdErr = np.std(losses) / math.sqrt(len(losses))
        log(lf, "Averaged relative error and std dev across models:   %f , %f " % (avgLoss, lossStdErr))
