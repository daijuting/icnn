from __future__ import print_function, division
import os
import torch
from skimage import io, transform
import numpy as np
import matplotlib.pyplot as plt
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils
from datetime import datetime


class DataArg(object):
	"""Data Argumentation"""

	def __call__(self, sample):
		image, labels, idx = sample['image'], sample['labels'], sample['index']

		
		np.random.seed(datetime.now().microsecond)
		Hshift = np.random.randint(-10,11)
		Vshift = np.random.randint(-10,11)
		angle = np.random.random()*30 - 15
		scale = np.random.random()*(1.1-0.9) + 0.9

		h,w,c = image.shape
		new_h, new_w = int(scale*h), int(scale*w)
		labels = labels.transpose(1,2,0) # process all labels in one go

		## Scale
		"""
		image = transform.resize(image, (new_h,new_w))
		labels = transform.resize(labels, (new_h,new_w))

		if new_h - h > 0:
			image = image[:(h-new_h),:,:]
			labels = labels[:(h-new_h),:,:]
		elif new_h - h < 0:
			image = np.pad(image, ((0,(h-new_h)), (0,0), (0,0)), mode='constant')
			labels = np.pad(labels, ((0,(h-new_h)), (0,0), (0,0)), mode='constant')

		if new_w - w > 0:
			image = image[:,:(w-new_w),:]
			labels = labels[:,:(w-new_w),:]
		elif new_w - w < 0:
			image = np.pad(image, ((0,0), (0,(w-new_w)), (0,0)), mode='constant')
			labels = np.pad(labels, ((0,0), (0,(w-new_w)), (0,0)), mode='constant')
		"""

		## Rotate
		image = transform.rotate(image, angle)
		labels = transform.rotate(labels, angle)

		## Shift
		#image = np.roll(image, [Vshift, Hshift], [0,1] )
		#labels = np.roll(labels, [Vshift, Hshift], [0,1] )

		if Vshift>0:
			image = np.pad(image[0:-Vshift,:,:], ((Vshift,0),(0,0),(0,0)), mode='constant')
			labels = np.pad(labels[0:-Vshift,:,:], ((Vshift,0),(0,0),(0,0)), mode='constant')
		else:
			image = np.pad(image[-Vshift:,:,:], ((0,-Vshift),(0,0),(0,0)), mode='constant')
			labels = np.pad(labels[-Vshift:,:,:], ((0,-Vshift),(0,0),(0,0)), mode='constant')

		if Hshift>0:
			image = np.pad(image[:,0:-Hshift,:], ((0,0),(Hshift,0),(0,0)), mode='constant')
			labels = np.pad(labels[:,0:-Hshift,:], ((0,0),(Hshift,0),(0,0)), mode='constant')
		else:
			image = np.pad(image[:,-Hshift:,:], ((0,0),(0,-Hshift),(0,0)), mode='constant')
			labels = np.pad(labels[:,-Hshift:,:], ((0,0),(0,-Hshift),(0,0)), mode='constant')


		labels = labels.transpose(2,0,1) # Rearrange labels back
		
		return {'image': image,	'labels': labels, 'index': idx}


class Rescale(object):
	"""Rescale the image in a sample to a given size.

	Args:
	output_size (tuple or int): Desired output size. If tuple, output is
	matched to output_size. If int, smaller of image edges is matched
	to output_size keeping aspect ratio the same.
	"""

	def __init__(self, output_size):
		assert isinstance(output_size, (int, tuple))
		self.output_size = output_size

	def __call__(self, sample):
		image, labels, idx = sample['image'], sample['labels'], sample['index']

		l,h,w = labels.shape
		_,_,c = image.shape
		if isinstance(self.output_size, int):
			if h > w:
				new_h, new_w = int(self.output_size * h / w), self.output_size
			else:
				new_h, new_w = self.output_size, int(self.output_size * w / h)
		else:
			new_h, new_w = self.output_size

		new_h, new_w = int(new_h), int(new_w)

		new_img = transform.resize(image, (new_h, new_w))
		new_labels = transform.resize(labels.transpose(1,2,0), (new_h,new_w)).transpose(2,0,1)

		# Put in a box with size 128 X 128 assuming aspect ratio is < 2.0 and output_size <= 64
		box_size = 128
		offset_y, offset_x = (box_size-new_h)//2, (box_size-new_w)//2

		pad_image = np.zeros([box_size,box_size,c])
		pad_labels = np.zeros([l, box_size,box_size])
		pad_image[offset_y:offset_y+new_h, offset_x:offset_x+new_w, :] = new_img
		pad_labels[:,offset_y:offset_y+new_h, offset_x:offset_x+new_w] = new_labels

		return {'image': pad_image, 'labels': pad_labels, 'index': idx}


class ToTensor(object):
	"""Convert ndarrays in sample to Tensors."""

	def __call__(self, sample):
		image, labels, idx = sample['image'], sample['labels'], sample['index']

		# swap color axis because
		# numpy image: H x W x C
		# torch image: C X H X W
		image = image.transpose((2, 0, 1))
		return {'image': torch.from_numpy(image).float(),
		'labels': torch.from_numpy(labels).float(),
		'index': idx}



class Invert(object):
	"""Flip image left to right"""

	def __call__(self, sample):
		image, labels, idx = sample['image'], sample['labels'], sample['index']
		if type(image).__module__==np.__name__:
			return  {'image':  np.flip(image, -2).copy(), 'labels': np.flip(labels, -1).copy(), 'index': idx}
		else:
			return {'image': image.flip(-1), 'labels': labels.flip(-1), 'index': idx}
		



class ImageDataset(Dataset):
	"""Image dataset."""
	def __init__(self, txt_file, root_dir, bg_indexs=set([]), fg_indexs=None, transform=None):
		"""
		Args:
		txt_file (string): Path to the txt file with list of image id, name.
		root_dir (string): Directory with all the images.
		transform (callable, optional): Optional transform to be applied
		on a sample.
		"""
		self.name_list = np.loadtxt(os.path.join(root_dir, txt_file), dtype='str', delimiter=',')
		self.root_dir = root_dir
		self.transform = transform

		if not fg_indexs:
			self.bg_indexs = sorted(bg_indexs)
			self.fg_indexs = sorted(set(range(11)).difference(bg_indexs))
		else:
			self.fg_indexs = sorted(fg_indexs)

	def __len__(self):
		return len(self.name_list)

	def __getitem__(self, idx):
		img_name = os.path.join(self.root_dir, 'images',
			self.name_list[idx, 1].strip() + '.jpg')

		image = np.array(io.imread(img_name), dtype=np.float)

		label_name = os.path.join(self.root_dir, 'labels',
			self.name_list[idx, 1].strip(), self.name_list[idx, 1].strip() + '_lbl%.2d.png')

		labels = []
		for i in self.fg_indexs:
			labels.append(io.imread(label_name%i))
		labels = np.array(labels, dtype=np.float)
		labels = np.concatenate((labels,[255.0-labels.sum(0)]), axis=0)
		
		sample = {'image': image, 'labels': labels, 'index':idx}
		if self.transform:
			sample = self.transform(sample)
		return sample