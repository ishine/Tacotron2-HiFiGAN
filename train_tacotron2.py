import numpy as np
import torch
from tensorboardX import SummaryWriter
# from torch import nn
from tqdm import tqdm

import config
from data_gen import TextMelLoader, TextMelCollate
from taco2models.loss_function import Tacotron2Loss
from taco2models.models import Tacotron2
from taco2models.optimizer import Tacotron2Optimizer
from utils_1 import parse_args, save_checkpoint, AverageMeter, get_logger, test


import os

os.environ['CUDA_VISIBLE_DEVICES'] ='7'

def train_net(args):
    torch.manual_seed(7)
    np.random.seed(7)
    checkpoint = args.checkpoint
    start_epoch = 0
    best_loss = float('inf')
    writer = SummaryWriter()
    epochs_since_improvement = 0

    # Initialize / load checkpoint
    if checkpoint is None:
        # model
        model = Tacotron2(config)
        print(model)
        # model = nn.DataParallel(model)

        # optimizer
        optimizer = Tacotron2Optimizer(
            torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.l2, betas=(0.9, 0.999), eps=1e-6))

    else:
        print(checkpoint)
        load_mode = 'p'
        if load_mode == 'dict':
            checkpoint = torch.load(checkpoint)
            model = checkpoint['model']
            epochs_since_improvement = checkpoint['epochs_since_improvement']
            model = checkpoint['model']
            optimizer = checkpoint['optimizer']
        else:
            checkpoint = torch.load(checkpoint)
            start_epoch = 0
            model = Tacotron2(config)
            model.load_state_dict(checkpoint)
        print(model)
        # epochs_since_improvement = checkpoint['epochs_since_improvement']
        # model = checkpoint['model']
        # optimizer = checkpoint['optimizer']
        optimizer = Tacotron2Optimizer(
            torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.l2, betas=(0.9, 0.999), eps=1e-6))

    logger = get_logger()

    # Move to GPU, if available
    model = model.to(config.device)

    criterion = Tacotron2Loss()

    collate_fn = TextMelCollate(config.n_frames_per_step)

    # Custom dataloaders
    # 创建一个能够访问(text,mel) pair的具体文件的接口，text是以一维数组的形式，mel是以二维数组的形式
    train_dataset = TextMelLoader(config.training_files, config) 

    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, collate_fn=collate_fn,
                                               pin_memory=True, shuffle=True, num_workers=args.num_workers)
    valid_dataset = TextMelLoader(config.validation_files, config)
    valid_loader = torch.utils.data.DataLoader(valid_dataset, batch_size=args.batch_size, collate_fn=collate_fn,
                                               pin_memory=True, shuffle=False, num_workers=args.num_workers)

    # Epochs
    for epoch in range(start_epoch, args.epochs):
        # One epoch's training
        
        train_loss = train(train_loader=train_loader,
                           model=model,
                           optimizer=optimizer,
                           criterion=criterion,
                           epoch=epoch,
                           logger=logger)
        writer.add_scalar('model/train_loss', train_loss, epoch)

        lr = optimizer.lr
        print('\nLearning rate: {}'.format(lr))
        writer.add_scalar('model/learning_rate', lr, epoch)
        step_num = optimizer.step_num
        print('Step num: {}\n'.format(step_num))
        

        # One epoch's validation
        valid_loss = valid(valid_loader=valid_loader,
                           model=model,
                           criterion=criterion,
                           logger=logger)
        writer.add_scalar('model/valid_loss', valid_loss, epoch)

        # Check if there was an improvement
        is_best = valid_loss < best_loss
        best_loss = min(valid_loss, best_loss)
        if not is_best:
            epochs_since_improvement += 1
            print("\nEpochs since last improvement: %d\n" % (epochs_since_improvement,))
        else:
            epochs_since_improvement = 0
        
        # Save checkpoint
        save_checkpoint(epoch, epochs_since_improvement, model, optimizer, best_loss, is_best)

        # alignments
        img_align = test(model, optimizer.step_num, valid_loss)
        writer.add_image('model/alignment', img_align, epoch, dataformats='HWC')


def train(train_loader, model, optimizer, criterion, epoch, logger):
    model.train()  # train mode (dropout and batchnorm is used)

    losses = AverageMeter()

    # Batches
    
    for i, batch in enumerate(train_loader):
        model.zero_grad()

        x, y = model.parse_batch(batch)

        # Forward prop.
        y_pred = model(x)

        loss = criterion(y_pred, y)

        # Back prop.
        optimizer.zero_grad()
        loss.backward()

        # Update weights
        optimizer.step()

        # Keep track of metrics
        losses.update(loss.item())
        torch.cuda.empty_cache()
        # Print status
        if i % args.print_freq == 0:
            logger.info('Epoch: [{0}][{1}/{2}]\t'
                        'Loss {loss.val:.4f} ({loss.avg:.4f})'.format(epoch, i, len(train_loader), loss=losses))

    return losses.avg


def valid(valid_loader, model, criterion, logger):
    model.eval()

    losses = AverageMeter()

    # Batches
    with torch.no_grad():
        for batch in tqdm(valid_loader):
            #model.zero_grad()
            x, y = model.parse_batch(batch)

            # Forward prop.
            y_pred = model(x)

            loss = criterion(y_pred, y)

            # Keep track of metrics
            print(loss.item())
            losses.update(loss.item())

        # Print status
        logger.info('\nValidation Loss {loss.val:.4f} ({loss.avg:.4f})\n'.format(loss=losses))

    return losses.avg


def main():
    global args
    args = parse_args()
    train_net(args)


if __name__ == '__main__':
    main()
