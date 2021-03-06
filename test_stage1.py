import torch
import torch.nn as nn
from model import ICNN
from utils import LOG_INFO
from preprocess import Rescale, ToTensor, ImageDataset, DataArg, FaceDetect
from torch.utils.data import DataLoader
from torchvision import transforms, utils
import argparse
import numpy as np
from scipy import ndimage
import matplotlib.pyplot as plt
import torch.nn.functional as F
import shutil
import pickle
from skimage import transform

parser = argparse.ArgumentParser()
parser.add_argument("--batch_size", default=10, type=int, help="Batch size")
args = parser.parse_args()
print(args)


if torch.cuda.is_available():
	device = torch.device("cuda")
else:
	device = torch.device("cpu")

resize_num = 64
warp_size = 128

test_dataset = ImageDataset(txt_file='testing.txt',
                                           root_dir='data/SmithCVPR2013_dataset_resized_' + str(resize_num),
                                           bg_indexs=set([0,1,10]),
                                           transform=transforms.Compose([ ToTensor() ]))
test_loader = DataLoader(test_dataset, batch_size=args.batch_size,
                        shuffle=True, num_workers=1)

unresized_dataset = ImageDataset(txt_file='testing.txt',
                                           root_dir='data/SmithCVPR2013_dataset_resized',
                                           bg_indexs=set([0,1,10]),
                                           transform=None)


def evaluate(model, loader, criterion):
	epoch_loss = 0
	model.eval()

	with torch.no_grad():
		for batch in loader:
			image, labels = batch['image'].to(device), batch['labels'].to(device)
			predictions = model(image)
			loss = criterion(predictions, labels.argmax(dim=1, keepdim=False))

			epoch_loss += loss.item()

	return epoch_loss / len(loader)


criterion = nn.CrossEntropyLoss()
criterion = criterion.to(device)

model = pickle.load(open('res/saved-model.pth', 'rb'))
model = model.to(device)
test_loss = evaluate(model, test_loader, criterion)
LOG_INFO('test loss = %.4f' % (test_loss))


def calculate_centroids(tensor):
	tensor = tensor.float() + 1e-10
	n,l,h,w = tensor.shape
	indexs_y = torch.from_numpy(np.arange(h)).float().to(tensor.device)
	indexs_x = torch.from_numpy(np.arange(w)).float().to(tensor.device)
	center_y = tensor.sum(3) * indexs_y.view(1,1,-1) 
	center_y = center_y.sum(2, keepdim=True) / tensor.sum([2,3]).view(n,l,1)
	center_x = tensor.sum(2) * indexs_x.view(1,1,-1)
	center_x = center_x.sum(2, keepdim=True) / tensor.sum([2,3]).view(n,l,1)
	return torch.cat([center_y, center_x], 2)


dist_error = np.zeros(9) # For each face part, last is background
count=0
def update_error(pred_centroids, orig_centroids):
	global dist_error, count
	count+= pred_centroids.shape[0]
	dist_error += torch.pow(pred_centroids - orig_centroids, 2).sum(dim=2).sqrt().sum(dim=0).to('cpu').numpy()


def show_error():
	global dist_error
	dist_error /=count
	parts = ['eyebrow1', 'eyebrow2', 'eye1', 'eye2', 'nose', 'mouth']
	
	print("\n\nDistance Error in resized image (in pixels) ... ")
	for i in range(len(parts)-1):
		print(parts[i], "%.2f pixels"%dist_error[i])
	print(parts[-1], "%.2f pixels"%dist_error[-3:].mean())

	print("Total Error: %.2f"%dist_error.mean())


def save_results(indexs, pred_centroids, orig_centroids, landmarks=None):
	pred_centroids = pred_centroids.detach().to('cpu').numpy()
	orig_centroids = orig_centroids.to('cpu').numpy()

	for i,idx in enumerate(indexs):
		img = np.array(unresized_dataset[idx]['image'], np.int)
		h,w,c = img.shape
		plt.imshow(img)

		#box_size = 128
		#new_h, new_w = [int(resize_num * h / w), resize_num] if h>w else [resize_num, int(resize_num * w / h)]
		#offset_y, offset_x = (box_size-new_h)//2, (box_size-new_w)//2

		new_h, new_w = resize_num, resize_num
		offset_y, offset_x = 0, 0

		if landmarks is None:
			plt.scatter(w/new_w*(orig_centroids[i,:-1, 1]-offset_x), h/new_h*(orig_centroids[i,:-1, 0]-offset_y), s=10, marker='x', c='r', label='Ground Truth')
			plt.scatter(w/new_w*(pred_centroids[i,:-1, 1]-offset_x), h/new_h*(pred_centroids[i,:-1, 0]-offset_y), s=10, marker='x', c='g', label='Predicted')
		else:
			orig_centroids[i] = np.flip( map_func1(landmarks[i], np.flip(orig_centroids[i], 1) ), 1)
			pred_centroids[i] = np.flip( map_func1(landmarks[i], np.flip(pred_centroids[i],1) ), 1)

			plt.scatter((orig_centroids[i,:-1, 1]-offset_x), (orig_centroids[i,:-1, 0]-offset_y), s=10, marker='x', c='r', label='Ground Truth')
			plt.scatter((pred_centroids[i,:-1, 1]-offset_x), (pred_centroids[i,:-1, 0]-offset_y), s=10, marker='x', c='g', label='Predicted')


		plt.legend()
		plt.savefig('res/'+unresized_dataset.name_list[idx, 1].strip() + '_loc.jpg')
		plt.close()

def save_maps(ground, pred, indexs):
	ground = F.one_hot(ground.argmax(1), model.L).transpose(3,1).transpose(2,3)[:,0:8,:,:].sum(1)
	pred = F.one_hot(pred.argmax(1), model.L).transpose(3,1).transpose(2,3)[:,0:8,:,:].sum(1)

	ground = np.uint8(ground.to('cpu').numpy() * 255)
	pred = np.uint8(pred.detach().to('cpu').numpy()*255)

	for i,idx in enumerate(indexs):
		plt.figure(figsize=(12.8, 9.6))

		ax = plt.subplot(1, 2, 1)
		ax.set_title("Ground Truth")
		plt.imshow(ground[i])

		ax = plt.subplot(1, 2, 2)
		ax.set_title("Predicted")
		plt.imshow(pred[i])

		plt.savefig('res/'+unresized_dataset.name_list[idx, 1].strip() + '_map.jpg')
		plt.close()


with torch.no_grad():
	for batch in test_loader:
		images, labels, indexs, landmarks = batch['image'].to(device), batch['labels'].to(device), batch['index'], batch['landmarks']

		# Original Centroids
		orig_labels = F.normalize(labels, 1)
		orig_centroids = calculate_centroids(orig_labels)

		# Predicted Centroids
		pred_labels = F.softmax(model(images), 1)
		pred_centroids = calculate_centroids(pred_labels)	

		# Update error stat
		update_error(pred_centroids, orig_centroids)

		# Save results
		save_results(indexs, pred_centroids, orig_centroids)
		save_maps(orig_labels, pred_labels, indexs)

show_error()