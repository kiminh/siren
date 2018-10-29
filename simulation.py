""" Simulation of online news consumption including recommendations.

A simulation framework  for the visualization and analysis of the effects of different recommenders systems. 
This simulation draws mainly on the work of Fleder and Hosanagar (2017). To account for the specificities 
of news consumption, it includes both users preferences and editorial priming as they interact in a 
news-webpage context. The simulation models two main components: users (preferences and behavior) 
and items (article content, publishing habits). Users interact with items and are recommended items
based on their interaction.

Example:
	An example 30 sim iterations for 200 users interacting with 100 items per iteration. Five 
	algorithms are of interest in this case Random,WeightedBPRMF,ItemKNN,MostPopular and UserKNN:

	$ python3 simulation.py -d 5 -u 200 -i 30 -t 100 -s 2 
	-r "Random,WeightedBPRMF,ItemKNN,MostPopular,UserKNN" 
	-f "temp" -n 5 -p 0.6 -N 6 -w "0.2,0.2,0.2,0.2,0.2" 
	-g "0.05,0.07,0.03,0.85,0.01"

Todo:
	* Add data export function.

"""

from __future__ import division
import numpy as np
from scipy import spatial
from scipy import stats
from scipy.stats import norm
from scipy.stats import chi2
import random
import time
import seaborn as sns
import pandas as pd
import pickle
import networkx as nx
from sklearn.datasets.samples_generator import make_blobs
from sklearn.mixture import GaussianMixture
import os
import sys, getopt
import copy
import json
import metrics
import matplotlib
import bisect
import collections
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from matplotlib.backends.qt_compat import QtCore, QtWidgets, is_pyqt5
import traceback, sys
from PyQt5.QtCore import QDateTime, Qt, QTimer
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateTimeEdit,
		QDial, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
		QProgressBar, QPushButton, QRadioButton, QScrollBar, QSizePolicy,
		QSlider, QSpinBox, QStyleFactory, QTableWidget, QTabWidget, QTextEdit,
		QVBoxLayout, QWidget)
from PyQt5.QtWidgets import *
from matplotlib.backends.qt_compat import QtCore, QtWidgets, is_pyqt5
if is_pyqt5():
	from matplotlib.backends.backend_qt5agg import (
		FigureCanvas, NavigationToolbar2QT as NavigationToolbar)
else:
	from matplotlib.backends.backend_qt4agg import (
		FigureCanvas, NavigationToolbar2QT as NavigationToolbar)
from matplotlib.figure import Figure

__author__ = 'Dimitrios  Bountouridis'

def cdf(weights):
	
	""" Cummulative density function.

	Used to convert topic weights into probabilities.

	Args:
		weights (list): An array of floats corresponding to weights 

	"""

	total = sum(weights)
	result = []
	cumsum = 0
	for w in weights:
		cumsum += w
		result.append(cumsum / total)
	return result

def selectClassFromDistribution(population, weights):
	""" Given a list of classes and corresponding weights randomly select a class.

	Args:
		population (list): A list of class names e.g. business, politics etc
		weights (list): Corresponding float weights for each class.

	"""

	assert len(population) == len(weights)
	cdf_vals = cdf(weights)
	x = random.random()
	idx = bisect.bisect(cdf_vals, x)
	return population[idx]

def standardize(num, precision = 2):
	""" Convert number to certain precision.

	Args:
		num (float): Number to be converted
		precision (int): Precision either 2 or 4 for now

	"""

	if precision == 2:
		return float("%.2f"%(num))
	if precision == 4:
		return float("%.4f"%(num))

def printj(text, comments=""):
	json = {"action":text,"comments":comments}
	print(json)

def euclideanDistance(A,B):
	""" Compute the pairwise distance between arrays of (x,y) points.

	We use a numpy version which is C++ based for the sake of efficiency.
	
	"""
	
	#spatial.distance.cdist(A, B, metric = 'euclidean')
	return np.sqrt(np.sum((np.array(A)[None, :] - np.array(B)[:, None])**2, -1)).T


class WorkerSignals(QObject):
	'''
	Defines the signals available from a running worker thread.

	Supported signals are:

	finished
		No data

	error
		`tuple` (exctype, value, traceback.format_exc() )

	result
		`object` data returned from processing, anything

	progress
		`int` indicating % progress

	'''
	finished = pyqtSignal()
	error = pyqtSignal(tuple)
	result = pyqtSignal(object)
	progress = pyqtSignal(float)

class Worker(QRunnable):
	'''
	Worker thread

	Inherits from QRunnable to handler worker thread setup, signals and wrap-up.

	:param callback: The function callback to run on this worker thread. Supplied args and 
					 kwargs will be passed through to the runner.
	:type callback: function
	:param args: Arguments to pass to the callback function
	:param kwargs: Keywords to pass to the callback function

	'''

	def __init__(self, fn, *args, **kwargs):
		super(Worker, self).__init__()

		# Store constructor arguments (re-used for processing)
		self.fn = fn
		self.args = args
		self.kwargs = kwargs
		self.signals = WorkerSignals()

		# Add the callback to our kwargs
		self.kwargs['progress_callback'] = self.signals.progress

	@pyqtSlot()
	def run(self):
		'''
		Initialise the runner function with passed args, kwargs.
		'''

		# Retrieve args/kwargs here; and fire processing using them
		try:
			result = self.fn(*self.args, **self.kwargs)
		except:
			traceback.print_exc()
			exctype, value = sys.exc_info()[:2]
			self.signals.error.emit((exctype, value, traceback.format_exc()))
		else:
			self.signals.result.emit(result)  # Return the result of the processing
		finally:
			self.signals.finished.emit()  # Done

class Users(object):
	""" The class for modeling the user preferences (users) and user behavior.

	The users object can be passed from simulation to simulation, allowing for
	different recommendation algorithms to be applied on. The default attributes
	correspond to findings reports on online news behavior (mostly Mitchell et 
	al 2017,'How Americans encounter, recall and act upon digital news').

	Todo:
		* Allow export of the data for analysis.

	"""

	def __init__(self):
		""" The initialization simply sets the default attributes.

		"""

		self.seed = 1

		self.totalNumberOfUsers = 200  # Total number of users                    
		self.percentageOfActiveUsersPI = 1.0 # Percentage of active users per iterations
 
		self.m = 0.05  # Percentage of the distance_ij covered when a user_i drifts towards an item_j

		# Choice attributes
		self.k = 20                          
		self.delta = 5
		self.beta = 0.9     
		self.meanSessionSize = 6                     

		# Awareness attributes
		self.theta = 0.07  # Proximity decay
		self.thetaDot = 0.5  # Prominence decay
		self.Lambda = 0.6  # Awareness balance between items in proximity and prominent items
		self.w = 40  # Maximum awareness pool size 
		self.Awareness = [] # User-item awareness matrix

		self.Users = []  # User preferences, (x,y) position of users on the attribute space
		self.UsersClass = []  # Users be assigned a class (center at attribute space)
		self.userVarietySeeking = []  # Users' willingness to drift
		self.X = False  # Tracking the X,Y position of users throught the simulation
		self.Y = False

	def generatePopulation(self):
		""" Genererating a population of users (user preferences and variety seeking).

		"""

		random.seed(self.seed)
		np.random.seed(self.seed)
		
		# Position on the attribute space. Uniform, bounded by 1-radius circle
		self.Users = np.random.uniform(-1,1,(self.totalNumberOfUsers,2))
		for i, user in enumerate(self.Users):
			while euclideanDistance([user], [[0,0]])[0][0]>1.1:
				user = np.random.uniform(-1,1,(1,2))[0]
			self.Users[i] = user
	
		# Variety seeking, willingness to drift. Arbitrary defined
		lower, upper = 0, 1
		mu, sigma = 0.1, 0.03
		X = stats.truncnorm( (lower - mu) / sigma, (upper - mu) / sigma, loc=mu, scale=sigma)
		self.userVarietySeeking = X.rvs(self.totalNumberOfUsers, random_state = self.seed)

		# Users can be assigned a class (most proxiamte attribute center), not currently used.
		#self.UsersClass = [gmm.predict([self.Users[i]*55])[0] for i in range(self.totalNumberOfUsers)]

		self.X = {i:[self.Users[i,0]] for i in range(self.totalNumberOfUsers)}
		self.Y = {i:[self.Users[i,1]] for i in range(self.totalNumberOfUsers)}
 
	def sessionSize(self):
		""" Draw the session size (amount of items to purchase) of each user at each iteration from a normal distribution.

		Returns:
			int: the session size

		"""

		return int(np.random.normal(self.meanSessionSize, 2))

	def subsetOfAvailableUsers(self):
		""" Randomly select a subset of the users.

		"""

		self.activeUserIndeces = np.arange(self.totalNumberOfUsers).tolist()
		random.shuffle(self.activeUserIndeces)
		self.activeUserIndeces = self.activeUserIndeces[:int(len(self.activeUserIndeces)*self.percentageOfActiveUsersPI)] 
		self.nonActiveUserIndeces = [ i  for i in np.arange(self.totalNumberOfUsers) if i not in self.activeUserIndeces]

	def computeAwarenessMatrix(self, Dij, ItemProminence, activeItemIndeces):
		""" Compute awareness from proximity and prominence (not considering availability, recommendations, history).

		Args:
			Dij (nparray): |Users| x |Items| distance matrix
			ItemProminence (nparray): |Items|-sized prominence vector 

		"""

		totalNumberOfItems = ItemProminence.shape[0]

		W = np.zeros([self.totalNumberOfUsers,totalNumberOfItems])
		W2 = W.copy() # for analysis purposes
		W3 = W.copy() # for analysis purposes
		for a in self.activeUserIndeces:
			W[a,activeItemIndeces] = self.Lambda*(-self.thetaDot*np.log(1-ItemProminence[activeItemIndeces])) + (1-self.Lambda)*np.exp(-(np.power(Dij[a,activeItemIndeces],2))/self.theta)
			W2[a,activeItemIndeces] = self.Lambda*(-self.thetaDot*np.log(1-ItemProminence[activeItemIndeces])) 
			W3[a,activeItemIndeces] = (1-self.Lambda)*np.exp(-(np.power(Dij[a,activeItemIndeces],2))/self.theta)
		R = np.random.rand(W.shape[0],W.shape[1])
		W = R<W
		self.Awareness, self.AwarenessOnlyPopular, self.AwarenessProximity =  W, W2, W3

	def choiceModule(self, Rec, w, distanceToItems, sessionSize, control = False):
		""" Selecting items to purchase for a single user.

		Args:
			Rec (list): List of items recommended to the user
			w (nparray): 1 x |Items| awareness of the user
			distanceToItems (nparray): 1 x |Items| distance of the user to the items
			sessionSize (int): number of items that the user will purchase

		Returns:
			 param1 (list): List of items that were selected including the stochastic component
			 param2 (list): List of items that were selected not including the stochastic component

		"""

		Similarity = -self.k*np.log(distanceToItems)  
		V = Similarity.copy()

		if not control: 
			# exponential ranking discount, from Vargas
			for k, r in enumerate(Rec):
				V[r] = Similarity[r] + self.delta*np.power(self.beta,k)

		# Introduce the stochastic component
		E = -np.log(-np.log([random.random() for v in range(len(V))]))
		U = V + E
		sel = np.where(w==1)[0]

		# with stochastic
		selected = np.argsort(U[sel])[::-1]
		
		# without stochastic
		selectedW = np.argsort(V[sel])[::-1]
		return sel[selected[:sessionSize]],sel[selectedW[:sessionSize]]
	
	def computeNewPositionOfUser(self, user, ChosenItems):
		""" Compute new position of a user given their purchased item(s).

		Args:
			user (int): Index of specific user.
			ChosenItems (list): (x,y) position array of items selected by the user.

		"""

		for itemPosition in ChosenItems:
			dist =  euclideanDistance([self.Users[user]], [itemPosition])[0]
			p = np.exp(-(np.power(dist,2))/(self.userVarietySeeking[user])) # based on the awareness formula
			B = np.array(self.Users[user])
			P = np.array(itemPosition)
			BP = P - B
			x,y = B + self.m*(random.random()<p)*BP 
			self.Users[user] = [x,y]
		self.X[user].append(x)
		self.Y[user].append(y)

	def showSettings(self):
		""" A simple function to print most of the attributes of the class.

		"""

		variables = [(key,type(self.__dict__[key])) for key in self.__dict__.keys() if (type(self.__dict__[key]) is str or type(self.__dict__[key]) is float or type(self.__dict__[key]) is int )]

		Json={ key: self.__dict__[key] for key,tp in variables }
		print(json.dumps(Json, sort_keys=True, indent=4))

class Items(object):
	""" The class for modeling the items' content (items) and prominence.

	The items object can be passed from simulation to simulation, allowing for
	different recommendation algorithms to be applied on. The default attributes
	correspond to findings reports on online news behavior (mostly Mitchell et 
	al 2017,'How Americans encounter, recall and act upon digital news').

	Todo:
		* Allow export of the data for analysis.

	"""
	def __init__(self):
		""" The initialization simply sets the default attributes.

		"""
		self.seed = 1
		self.numberOfNewItemsPI = 100  # The number of new items added per iteration
		self.totalNumberOfItems = False  # The total number of items (relates to the number of iterations)
		self.percentageOfActiveItems = False  
							
		# Topics, frequency weights and prominence weights. We use topics instead of "classes" here.
		self.topics = ["entertainment","business","sport","politics","tech"]
		self.topicsProminence = [0.05,0.07,0.03,0.85,0.01] 
		self.topicsFrequency = [0.2, 0.2, 0.2, 0.2, 0.2]

		self.p = 0.1  # Slope of salience decrease function

		self.Items = []  # The items' content (x,y) position on the attribute space
		self.ItemsClass = []  # The items' class corresponds to the most prominent topic
		self.ItemsFeatures = False  # The items' feature vector
		self.ItemsDistances = False  # |Items|x|Items| distance matrix
		self.ItemsOrderOfAppearance = False  # Random order of appearance at each iteration
		self.ItemProminence = False  #  Item's prominence
		self.ItemLifespan = False  # Items' age (in iterations)
		self.hasBeenRecommended = False  # Binary matrix holding whether each items has been recommended

	def generatePopulation(self, totalNumberOfIterations):
		""" Genererating a population of items (items' content and initial prominence).

		"""

		random.seed(self.seed)
		np.random.seed(self.seed)

		# Compute number of total items in the simulation
		self.totalNumberOfItems = totalNumberOfIterations*self.numberOfNewItemsPI                    
		self.percentageOfActiveItems = self.numberOfNewItemsPI/self.totalNumberOfItems

		# Apply GMM on items/articles from the BBC data
		R, S = [5,1,6,7], [5,2,28,28]
		r = int(random.random()*4)
		printj("Item space projection selected:",R[r])
		(X,labels,topicClasses) = pickle.load(open('BBC data/t-SNE-projection'+str(R[r])+'.pkl','rb'))
		gmm = GaussianMixture(n_components=5, random_state=S[r]).fit(X)
		
		# Normalize topic weights to sum into 1 (CBF)
		self.topicsFrequency = [np.round(i,decimals=1) for i in self.topicsFrequency/np.sum(self.topicsFrequency)]
		
		# Generate items/articles from the BBC data projection
		samples_, classes_ = gmm.sample(self.totalNumberOfItems*10)
		for c, category in enumerate(self.topics):
			selection = samples_[np.where(classes_ == c)][:int(self.topicsFrequency[c]*self.totalNumberOfItems)]
			if len(self.Items) == 0:
				self.Items = np.array(selection)
			else:
				self.Items = np.append(self.Items, selection, axis=0)
			self.ItemsClass+=[c for i in range(len(selection))]
		self.ItemsClass = np.array(self.ItemsClass)
		self.ItemsFeatures = gmm.predict_proba(self.Items)
		self.Items = self.Items/55  # Scale down to -1, 1 range
		
		# Cosine distance between item features
		self.ItemsDistances = spatial.distance.cdist(self.ItemsFeatures, self.ItemsFeatures, metric='cosine')

		# Generate a random order of item availability
		self.ItemsOrderOfAppearance = np.arange(self.totalNumberOfItems).tolist()
		random.shuffle(self.ItemsOrderOfAppearance)
	
		# Initial prominence
		self.initialProminceZ0()
		self.ItemProminence = self.ItemsInitialProminence.copy()

		# Lifespan, item age
		self.ItemLifespan = np.ones(self.totalNumberOfItems)

		# Has been recommended before
		self.hasBeenRecommended = np.zeros(self.totalNumberOfItems)

	def prominenceFunction(self, initialProminence, life):
		""" Decrease of item prominence, linear function.

		Args:
			initialProminence (float): The initial prominence of the item
			life (int): The item's age (in iterations)

		Returns:
			param1 (float): New prominence value

		"""

		x = life
		y = (-self.p*(x-1)+1)*initialProminence
		return max([y, 0])

	def subsetOfAvailableItems(self,iteration):
		""" Randomly select a subset of the items. 

		The random order of appearance has already been defined in ItemsOrderOfAppearance. The function simply 
		extends the size of the activeItemIndeces array.

		Args:
			iteration (int): the current simulation iteration

		"""

		self.activeItemIndeces =[j for j in self.ItemsOrderOfAppearance[:(iteration+1)*int(self.totalNumberOfItems*self.percentageOfActiveItems)] if self.ItemProminence[j]>0]
		self.nonActiveItemIndeces = [ i  for i in np.arange(self.totalNumberOfItems) if i not in self.activeItemIndeces]

	def updateLifespanAndProminence(self):
		""" Update the lifespan and promince of the items.

		"""

		self.ItemLifespan[self.activeItemIndeces] = self.ItemLifespan[self.activeItemIndeces]+1
		
		for a in self.activeItemIndeces:
			self.ItemProminence[a] = self.prominenceFunction(self.ItemsInitialProminence[a],self.ItemLifespan[a])
		
	def initialProminceZ0(self):
		""" Generate initial item prominence based on the topic weights and topic prominence.

		"""

		self.topicsProminence = [np.round(i,decimals=2) for i in self.topicsProminence/np.sum(self.topicsProminence)]
		counts = dict(zip(self.topics, [len(np.where(self.ItemsClass==i)[0]) for i,c in enumerate(self.topics) ]))
		items = len(self.ItemsClass)
		population = self.topics
		
		# Chi square distribution with two degrees of freedom. Other power-law distributions can be used.
		df = 2
		mean, var, skew, kurt = chi2.stats(df, moments='mvsk')
		x = np.linspace(chi2.ppf(0.01, df), chi2.ppf(0.99, df), items)
		rv = chi2(df)
		
		Z = {}
		for c in self.topics: Z.update({c:[]})		
		
		# Assign topic to z prominence without replacement
		for i in rv.pdf(x):
			c = selectClassFromDistribution(population, self.topicsProminence)
			while counts[c]<=0:
				c = selectClassFromDistribution(population, self.topicsProminence)
			counts[c]-=1
			Z[c].append(i/0.5)

		self.ItemsInitialProminence = np.zeros(self.totalNumberOfItems)
		for c, category in enumerate(self.topics): 
			indeces = np.where(self.ItemsClass==c)[0]
			self.ItemsInitialProminence[indeces] = Z[category]	

		# # plotting
		# min_= np.min([len(Z[i]) for i in Z.keys()])
		# x = []
		# for k in Z.keys():
		# 	x.append(Z[k][:min_])
		# print(np.array(x).T)
		# # set sns context
		# sns.set_context("notebook", font_scale=2, rc={"lines.linewidth": 1.0,'xtick.labelsize': 32, 'axes.labelsize': 32})
		# sns.set(style="whitegrid")
		# sns.set_style({'font.family': 'serif', 'font.serif': ['Times New Roman']})
		# matplotlib.pyplot.rc('text', usetex=True)
		# matplotlib.pyplot.rc('font', family='serif',size=20)
		# flatui = sns.color_palette("husl", 8)
		# #fig, ax = plt.subplots()
		# fig, axes = matplotlib.pyplot.subplots(nrows=1, ncols=1, figsize=(8, 6))
		# ax0= axes
		# cmaps= ['Blues','Reds','Greens','Oranges','Greys']
		# t = ["entertainment","business","sport","politics","tech"]
		# colors = [sns.color_palette(cmaps[i])[-2] for i in range(len(t))]
		# ax0.hist(x, 10, histtype='bar',stacked=True, color=colors,label=categories)
		# ax0.legend(prop={'size': 18})
		# for tick in ax0.xaxis.get_major_ticks():
		# 	tick.label.set_fontsize(18)
		# for tick in ax0.yaxis.get_major_ticks():
		# 	tick.label.set_fontsize(0)
		# ax0.set_xlabel("$z^0$",fontsize=20)
		# ax0.set_ylabel("")
		# sns.despine()
		# matplotlib.pyplot.show()

	def showSettings(self):
		""" A simple function to print most of the attributes of the class.

		"""
		variables = [key for key in self.__dict__.keys() if (type(self.__dict__[key]) is str or type(self.__dict__[key]) is float or type(self.__dict__[key]) is int or type(self.__dict__[key]) is list and len(self.__dict__[key])<10)]
		old = self.__dict__
		Json={ key: old[key] for key in variables }
		print(json.dumps(Json, sort_keys=True, indent=4))

class Recommendations(object):
	def __init__(self):
		self.outfolder = "temp"
		self.SalesHistory = []
		self.U = []
		self.I = []
		self.algorithm = False
		self.n = 5 

	def setData(self, U, I, algorithm, SalesHistory):
		self.U, self.I, self.algorithm, self.SalesHistory = U, I, algorithm, SalesHistory

	def exportToMMLdocuments(self):
		""" Export users' features, items' content and user-item purchase history for MyMediaLite.

		MyMediaLite has a specific binary input format for user-, item-attributes: the attribute
		either belongs or does not belong to an item or user. To accommodate for that we had to 
		take some liberties and convert the user's feature vector and item's feature vector into
		a binary format.


		"""

		np.savetxt(self.outfolder + "/users.csv", np.array([i for i in range(self.U.totalNumberOfUsers)]), delimiter=",", fmt='%d')

		F = []
		for user in range(self.SalesHistory.shape[0]):
			purchases = self.SalesHistory[user,:]
			items = np.where(purchases==1)[0]
			userf = self.I.ItemsFeatures[items]
			userfm = np.mean(userf,axis=0)
			userfm = userfm/np.max(userfm)
			feat = np.where(userfm>0.33)[0]
			for f in feat: F.append([int(user),int(f)])
		np.savetxt(self.outfolder + "/users_attributes.csv", np.array(F), delimiter=",", fmt='%d')

		if self.I.activeItemIndeces:
			p = np.where(self.SalesHistory>=1)
			z = zip(p[0],p[1])
			l = [[i,j] for i,j in z if j in self.I.activeItemIndeces]
			np.savetxt(self.outfolder + "/positive_only_feedback.csv", np.array(l), delimiter=",", fmt='%d')

		if not self.I.activeItemIndeces: self.I.activeItemIndeces = [i for i in range(self.I.totalNumberOfItems)]
		d = []
		for i in self.I.activeItemIndeces:
			feat = np.where(self.I.ItemsFeatures[i]/np.max(self.I.ItemsFeatures[i])>0.33)[0]
			for f in feat: d.append([int(i),int(f)])
		np.savetxt(self.outfolder + "/items_attributes.csv", np.array(d), delimiter=",", fmt='%d')
	
	def mmlRecommendation(self):
		""" A wrapper around the MyMediaLite toolbox

		Returns:
			recommendations (dict): A {user:[recommended items]} dictionary 
		
		"""

		command = "mono MyMediaLite/item_recommendation.exe --training-file=" + self.outfolder + "/positive_only_feedback.csv --item-attributes=" + self.outfolder + "/items_attributes.csv --recommender="+self.algorithm+" --predict-items-number="+str(self.n)+" --prediction-file=" + self.outfolder + "/output.txt --user-attributes=" + self.outfolder + "/users_attributes.csv" # --random-seed="+str(int(self.seed*random.random()))
		os.system(command)
		
		# Parse output
		f = open( self.outfolder + "/output.txt","r").read() 
		f = f.split("\n")
		recommendations = {}
		for line in f[:-1]:
			l = line.split("\t")
			user_id = int(l[0])
			l1 = l[1].replace("[","").replace("]","").split(",")
			rec = [int(i.split(":")[0]) for i in l1]
			recommendations.update({user_id:rec})
		return recommendations 


class SimulationGUI(QDialog):
	""" The simulation class takes users and items and simulates their interaction.

	The simulation can include recommendations (currently using a MyMediaLite wrapper).
	Alternative toolboxes can be used. The simulation class also stores results for 
	analysis and computes diversity metrics (based on the PhD thesis of Vargas).

	"""

	"""
		GUI functions

	"""
	def __init__(self, *args, **kwargs):
		super(SimulationGUI, self).__init__(*args, **kwargs)

		self.originalPalette = QApplication.palette()

		defaultPushButton = QPushButton("Start")
		defaultPushButton.setDefault(True)
		defaultPushButton.clicked.connect(self.onStartButtonClicked)

		self.createTopLeftGroupBox()
		self.createTopMiddleGroupBox()
		self.createTopRightGroupBox()
		self.createProgressBar()
		self.createFigures()

		topLayout = QHBoxLayout()
		topLabel = QLabel("A toolbox for simulating user interaction with personalized news recommendations in a typical online news environment.")
		topLayout.addWidget(topLabel)
		mainLayout = QGridLayout()
		mainLayout.addLayout(topLayout, 0, 0, 1, 3)
		mainLayout.addWidget(self.topLeftGroupBox, 1, 0)
		mainLayout.addWidget(self.topMiddleGroupBox, 1, 1)
		mainLayout.addWidget(self.topRightGroupBox, 1, 2)
		mainLayout.addWidget(self.figures, 4, 0, 1, 3)
		mainLayout.addWidget(self.progressBar, 3, 0, 1, 3)
		mainLayout.addWidget(defaultPushButton, 2, 0, 1, 3)
		mainLayout.setRowStretch(1, 1)
		mainLayout.setRowStretch(2, 1)
		mainLayout.setColumnStretch(0, 1)
		mainLayout.setColumnStretch(1, 1)
		mainLayout.setColumnStretch(2, 1)
		self.setLayout(mainLayout)

		self.setWindowTitle("SIREN")
		#self.changeStyle('Windows')

		self.plotter = None 
		self.thread = None

		self.threadpool = QThreadPool()
		print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
		# self.timer = QTimer()
		# self.timer.setInterval(1000)
		# self.timer.timeout.connect(self.recurring_timer)
		# self.timer.start()

	# Progress bar
	def createProgressBar(self):
		self.progressBar = QProgressBar()
		self.progressBar.setRange(0, 100)
		self.progressBar.setValue(0)

		#timer = QTimer(self)
		#timer.timeout.connect(self.advanceProgressBar)
		#timer.start(1000)

	# Figures
	def createFigures(self):
		self.figures = QGroupBox("Figures")

		dynamic_canvas1 = FigureCanvas(Figure(figsize=(5, 4)))
		self._dynamic_ax1 = dynamic_canvas1.figure.subplots()

		dynamic_canvas2 = FigureCanvas(Figure(figsize=(5, 4)))
		self._dynamic_ax2 = dynamic_canvas2.figure.subplots()

		self._dynamic_ax1.clear()
		self._dynamic_ax2.clear()
		axis_font = {'fontname':'Arial', 'size':'8'}

		self._dynamic_ax2.set_xlabel("Days", **axis_font)
		self._dynamic_ax2.set_ylabel("EPC", **axis_font)
		self._dynamic_ax2.set_title("Long-tail diversity measured using the Expected Popularity Complement (EPC) metric of Vargas (2015).", **axis_font)

		layout = QGridLayout()
		layout.addWidget(dynamic_canvas1, 0, 0)
		layout.addWidget(dynamic_canvas2, 0, 1)
		layout.setRowStretch(1, 1)
		layout.setRowStretch(2, 1)
		layout.setColumnStretch(0, 1)
		layout.setColumnStretch(1, 1)
		self.figures.setLayout(layout)

	# Recommendation settings
	def createTopLeftGroupBox(self):
		self.topLeftGroupBox = QGroupBox("Recommender settings")

		comboBoxAlgorithms = QListWidget(self.topLeftGroupBox)
		comboBoxAlgorithms.setSelectionMode(QAbstractItemView.MultiSelection)
		comboBoxAlgorithmsLabel = QLabel("&Rec algorithms (scroll for more):")
		comboBoxAlgorithmsLabel.setBuddy(comboBoxAlgorithms)
		comboBoxAlgorithms.addItems(["BPRMF", "ItemAttributeKNN", "ItemKNN", "MostPopular", "Random", "UserAttributeKNN","UserKNN",
    "WRMF","MultiCoreBPRMF", "SoftMarginRankingMF", "WeightedBPRMF", "MostPopularByAttributes", "BPRSLIM",
    "LeastSquareSLIM"])

		spinBoxSalience = QSpinBox(self.topLeftGroupBox)
		spinBoxSalienceLabel = QLabel("&Rec salience:")
		spinBoxSalienceLabel.setBuddy(spinBoxSalience)
		spinBoxSalience.setValue(5)

		spinBoxDays = QSpinBox(self.topLeftGroupBox)
		spinBoxDaysLabel = QLabel("&Days:")
		spinBoxDaysLabel.setBuddy(spinBoxDays)
		spinBoxDays.setValue(20)

		spinBoxRecArticles = QSpinBox(self.topLeftGroupBox)
		spinBoxRecArticlesLabel = QLabel("&Recommended articles per day:")
		spinBoxRecArticlesLabel.setBuddy(spinBoxRecArticles)
		spinBoxRecArticles.setValue(5)

		layout = QVBoxLayout()
		layout.addWidget(comboBoxAlgorithmsLabel)
		layout.addWidget(comboBoxAlgorithms)
		layout.addWidget(spinBoxSalienceLabel)
		layout.addWidget(spinBoxSalience)
		layout.addWidget(spinBoxDaysLabel)
		layout.addWidget(spinBoxDays)
		layout.addWidget(spinBoxRecArticlesLabel)
		layout.addWidget(spinBoxRecArticles)

		layout.addStretch(1)
		self.topLeftGroupBox.setLayout(layout)

	# Article settings
	def createTopMiddleGroupBox(self):
		self.topMiddleGroupBox = QGroupBox("Article settings")

		spinBoxPubArticles = QSpinBox(self.topMiddleGroupBox)
		spinBoxPubArticles.setRange(10,500)
		spinBoxPubArticles.setValue(100)
		spinBoxPubArticlesLabel = QLabel("&Published articles per day:")
		spinBoxPubArticlesLabel.setBuddy(spinBoxPubArticles)

		sliderEnt = QSlider(Qt.Horizontal, self.topMiddleGroupBox)
		sliderEnt.setRange(10, 100)
		sliderEnt.setValue(20)
		sliderEntLabel = QLabel("&Entertainment:")
		sliderEntLabel.setBuddy(sliderEnt)

		sliderBus = QSlider(Qt.Horizontal, self.topMiddleGroupBox)
		sliderBus.setValue(40)
		sliderBusLabel = QLabel("&Business:")
		sliderBusLabel.setBuddy(sliderBus)

		layout = QVBoxLayout()
		#layout.addWidget(defaultPushButton)
		layout.addWidget(spinBoxPubArticlesLabel)
		layout.addWidget(spinBoxPubArticles)
		layout.addWidget(sliderEntLabel)
		layout.addWidget(sliderEnt)
		layout.addWidget(sliderBusLabel)
		layout.addWidget(sliderBus)

		layout.addStretch(1)
		self.topMiddleGroupBox.setLayout(layout)

	# User settings
	def createTopRightGroupBox(self):
		self.topRightGroupBox = QGroupBox("User settings")

		spinBoxUsers = QSpinBox(self.topRightGroupBox)
		spinBoxUsers.setRange(10,500)
		spinBoxUsers.setValue(100)
		spinBoxUsersLabel = QLabel("&Active users per day:")
		spinBoxUsersLabel.setBuddy(spinBoxUsers)

		spinBoxUsersArticles = QSpinBox(self.topRightGroupBox)
		spinBoxUsersArticles.setRange(1,50)
		spinBoxUsersArticles.setValue(6)
		spinBoxUsersArticlesLabel = QLabel("&Average read articles per day:")
		spinBoxUsersArticlesLabel.setBuddy(spinBoxUsersArticles)

		sliderFocus = QSlider(Qt.Horizontal, self.topMiddleGroupBox)
		sliderFocus.setRange(5, 100)
		sliderFocus.setValue(80)
		sliderFocusLabel = QLabel("&Reading focus:")
		sliderFocusLabel.setBuddy(sliderFocus)

		layout = QVBoxLayout()
		#layout.addWidget(defaultPushButton)
		layout.addWidget(spinBoxUsersLabel)
		layout.addWidget(spinBoxUsers)
		layout.addWidget(spinBoxUsersArticlesLabel)
		layout.addWidget(spinBoxUsersArticles)
		layout.addWidget(sliderFocusLabel)
		layout.addWidget(sliderFocus)

		layout.addStretch(1)
		self.topRightGroupBox.setLayout(layout)


	"""
		Multi-thread functions 

	"""

	def progress_fn(self, progress_):
		print(progress_, " done")
		curVal = self.progressBar.value()
		maxVal = self.progressBar.maximum()
		self.progressBar.setValue(progress_*100)

		# Load diversity metrics data
		df = pd.read_pickle(self.outfolder + "/metrics analysis.pkl")

		self._dynamic_ax1.clear()
		self._dynamic_ax2.clear()
		axis_font = {'fontname':'Arial', 'size':'8'}

		self._dynamic_ax1.set_xlabel("Days", **axis_font)
		self._dynamic_ax1.set_ylabel("EPC", **axis_font)
		self._dynamic_ax1.set_title("Long-tail diversity measured using the Expected Popularity Complement (EPC) metric of Vargas (2015).", **axis_font)

		# Shift the sinusoid as a function of time.
		for algorithm in self.algorithms:
			if algorithm=="Control":continue
			y = df[algorithm]["EPC"]
			x = [i for i in range(len(y))]
			self._dynamic_ax1.plot(x, y, label=algorithm)

			y = df[algorithm]["EPD"]
			x = [i for i in range(len(y))]
			self._dynamic_ax2.plot(x, y, label=algorithm)


		self._dynamic_ax1.legend()
		self._dynamic_ax2.legend()
		self._dynamic_ax1.figure.canvas.draw()
		self._dynamic_ax1.figure.canvas.draw_idle()
		self._dynamic_ax2.figure.canvas.draw()
		self._dynamic_ax2.figure.canvas.draw_idle()


	def print_output(self):
		"""
			Empty
		"""
		return False

	def simulation_complete(self):
		"""
			Empty
		"""

		return False

	def onStartButtonClicked(self):

		# Initialize the simulation
		settings = {"Number of active users per day": str(200),
			"Days" : str(20), 
			"seed": int(1),
			"Recommender salience": str(5),
			"Number of published articles per day": str(100),
			"outfolder": "temp",
			"Number of recommended articles per day": str(5),
			"Average read articles per day": str(6),
			"Reading focus": float(0.8),
			"Recommender algorithms": "Random,BPRMF",
			"Overall topic weights": [0.2, 0.2, 0.2, 0.2, 0.2],
			"Overall topic prominence": [0.2, 0.2, 0.2, 0.9, 0.2]}
		self.initWithSettings(settings)

		# Pass the function to execute
		worker = Worker(self.runSimulation) # Any other args, kwargs are passed to the run function
		worker.signals.result.connect(self.print_output)
		worker.signals.finished.connect(self.simulation_complete)
		worker.signals.progress.connect(self.progress_fn)

		# Execute
		self.threadpool.start(worker)


	"""
		Main simulation functions
	
	"""
	def exportAnalysisDataAfterIteration(self):
		""" Export some analysis data to dataframes.

		"""


		# Metrics output
		df = pd.DataFrame(self.diversityMetrics)
		df.to_pickle(self.outfolder + "/metrics analysis.pkl")

	
	def awarenessModule(self, epoch):
		""" This function computes the awareness of each user.

		While the proximity/prominence awareness is computed in the user class, the current function
		updates that awareness to accommodate for the non-available items and those that the user
		has purchased before. The number of items in the awareness is also limited.

		Args:
			epoch (int): The current iteration. 
		
		"""

		self.U.subsetOfAvailableUsers()
		self.I.subsetOfAvailableItems(epoch)
		self.U.computeAwarenessMatrix(self.D, self.I.ItemProminence, self.I.activeItemIndeces)
		
		# Adjust for availability 
		self.U.Awareness[:,self.I.nonActiveItemIndeces] = 0 

		# Adjust for purchase history
		self.U.Awareness = self.U.Awareness - self.SalesHistory>0

		# Adjust for maximum number of items in awareness
		for a in range(self.U.totalNumberOfUsers):
			w = np.where(self.U.Awareness[a,:]==1)[0]
			if len(w)>self.U.w:
				windex = w.tolist()
				random.shuffle(windex)
				self.U.Awareness[a,:] = np.zeros(self.I.totalNumberOfItems)
				self.U.Awareness[a,windex[:self.U.w]] = 1	
		
	def temporalAdaptationsModule(self, epoch):
		""" Update the user-items distances and item- lifespand and prominence.

		Todo:
			* Updating the item-distance only for items that matter

		"""	
	
		self.I.updateLifespanAndProminence()

		# We compute this here so that we update the distances between users and not all the items
		self.I.subsetOfAvailableItems(epoch+1)
	

		if self.algorithm is not "Control":
			D =  euclideanDistance(self.U.Users, self.I.Items[self.I.activeItemIndeces])
			# If you use only a percentage of users then adjust this function
			for u in range(self.U.totalNumberOfUsers): self.D[u,self.I.activeItemIndeces] = D[u,:]
		
	def runSimulation(self, progress_callback):
		""" The main simulation function.

		For different simulation instantiations to run on the same random order of items
		the iterationRange should be the same.

		Args:
			iterationRange (list): The iteration range for the current simulation

		"""

		# For all recommenders (starting with the "Control")
		for self.algorithm in self.algorithms:

			# Initialize the iterations range and input data for the recommender
			days = int(self.totalNumberOfIterations/2)
			if self.algorithm == "Control":
				self.iterationRange = [i for i in range(days)]
			else:
				# Copy the users, items and their interactions from the control period
				self.U = copy.deepcopy(ControlU)
				self.I = copy.deepcopy(ControlI)
				self.D = ControlD.copy()  # Start from the control distances between items and users
				self.SalesHistory = ControlHistory.copy()  # Start from the control sale history
				# self.ControlHistory = ControlHistory.copy()  # We use a copy of th
				self.iterationRange = [i for i in range(days,days*2)]

			# Start the simulation for the current recommender				
			for epoch_index, epoch in enumerate(self.iterationRange):

				SalesHistoryBefore = self.SalesHistory.copy()
				print(epoch_index/len(self.iterationRange))
				progress_callback.emit((epoch_index+1)/len(self.iterationRange))

				printj(self.algorithm+": Awareness...")				
				self.awarenessModule(epoch)
				InitialAwareness = self.U.Awareness.copy()

				# Recommendation module 
				if self.algorithm is not "Control":
					printj(self.algorithm+": Recommendations...")

					# Call the recommendation object
					self.Rec.setData(self.U, self.I, self.algorithm, self.SalesHistory)
					self.Rec.exportToMMLdocuments()
					recommendations = self.Rec.mmlRecommendation()
		
					# Add recommendations to each user's awareness pool			
					for user in self.U.activeUserIndeces:
						Rec=np.array([-1])
						
						if self.algorithm is not "Control":
							if user not in recommendations.keys():
								printj(" -- Nothing to recommend -- to user ",user)
								continue
							Rec = recommendations[user]
							self.I.hasBeenRecommended[Rec] = 1
							self.U.Awareness[user, Rec] = 1

							# If recommended but previously purchased, minimize the awareness
							self.U.Awareness[user, np.where(self.SalesHistory[user,Rec]>0)[0] ] = 0  	

				# Choice 
				printj(self.algorithm+": Choice...")
				for user in self.U.activeUserIndeces:
					Rec=np.array([-1])
					
					if self.algorithm is not "Control":
						if user not in recommendations.keys():
							printj(" -- Nothing to recommend -- to user ",user)
							continue
						Rec = recommendations[user]
					
					indecesOfChosenItems,indecesOfChosenItemsW =  self.U.choiceModule(Rec, 
						self.U.Awareness[user,:], 
						self.D[user,:], 
						self.U.sessionSize(), 
						control = self.algorithm=="Control")

					# Add item purchase to histories
					self.SalesHistory[user, indecesOfChosenItems] += 1		
							
					# Compute new user position 
					if self.algorithm is not "Control" and len(indecesOfChosenItems)>0:
						self.U.computeNewPositionOfUser(user, self.I.Items[indecesOfChosenItems])

					# Store some data for analysis
					for i,indexOfChosenItem in enumerate(indecesOfChosenItems):
						indexOfChosenItemW = indecesOfChosenItemsW[i]
						self.AnaylysisInteractionData.append([epoch_index, 
							user, 
							self.algorithm,
							indexOfChosenItem,
							self.I.ItemLifespan[indexOfChosenItem], 
							self.I.ItemProminence[indexOfChosenItem],
							self.I.topics[self.I.ItemsClass[indexOfChosenItem]],
							indexOfChosenItem in Rec, 
							indexOfChosenItem == indexOfChosenItemW,
							self.I.hasBeenRecommended[indexOfChosenItemW],
							self.I.ItemsClass[indexOfChosenItem]==self.I.ItemsClass[indexOfChosenItemW] , 
							0,
							0, 
							InitialAwareness[user,indexOfChosenItem] ])

				# Temporal adaptations
				printj(self.algorithm+": Temporal adaptations...")	
				self.temporalAdaptationsModule(epoch)

				# Compute diversity metrics		
				if self.algorithm is not "Control":
					printj(self.algorithm+": Diversity metrics...")
					
					met = metrics.metrics(SalesHistoryBefore, recommendations, self.I.ItemsFeatures, self.I.ItemsDistances, self.SalesHistory)
					#met.update({"Gini": metrics.computeGinis(self.SalesHistory,self.ControlHistory)})
					for key in met.keys():
						self.diversityMetrics[self.algorithm][key].append(met[key])
						print(self.diversityMetrics)

				# # Show stats on screen and save json for interface
				# printj(self.algorithm+": Exporting...")
				# self.exportJsonForOnlineInterface(epoch, epoch_index, self.iterationRange, SalesHistoryBefore)

				# Save results
				printj(self.algorithm+": Exporting iteration data...")
				self.exportAnalysisDataAfterIteration()
				
				# After the control period is over, we store its data to be used by the other rec algorithms
				if self.algorithm == "Control":
					ControlU = copy.deepcopy(self.U)
					ControlI = copy.deepcopy(self.I)
					ControlD = self.D.copy()  # Start from the control distances between items and users
					ControlHistory = self.SalesHistory.copy()  # We use a copy of th


			
				
	def plot2D(self, drift = False, output = "initial-users-products.pdf", storeOnly = True):
		""" Plotting the users-items on the attribute space.

		Args:
			drift (bool): Whether the user drift should be plotted (it is time consuming)
			output (str): The output pdf file
			storeOnly (bool): Whether the plot should be shown

		"""

		sns.set_context("notebook", font_scale=1.6, rc={"lines.linewidth": 1.0,'xtick.labelsize': 32, 'axes.labelsize': 32})
		sns.set(style="whitegrid")
		sns.set_style({'font.family': 'serif', 'font.serif': ['Times New Roman']})
		flatui = sns.color_palette("husl", 8)
		f, ax = matplotlib.pyplot.subplots(1,1, figsize=(6,6), sharey=True)

		cmaps= ['Blues','Reds','Greens','Oranges','Greys']
		colors = [sns.color_palette(cmaps[i])[-2] for i in range(len(self.I.topics))]
		
		# If no sales history yet, display items with prominence as 3rd dimension
		if np.sum(np.sum(self.SalesHistory))==0:
			n = np.sum(self.SalesHistory,axis=0)
			for i in range(self.I.totalNumberOfItems): 
				color = colors[self.I.ItemsClass[i]]
				s = self.I.ItemProminence[i]*40
				ax.scatter(self.I.Items[i,0], self.I.Items[i,1], marker='o', c=color,s=s,alpha=0.5)
		else:
			# KDE plot
			n = np.sum(self.SalesHistory,axis=0)
			for cat in range(len(self.I.topics)): # 5 topic spaces
				indeces=np.where(self.I.ItemsClass==cat)[0]
				x = []
				for i in indeces:
					if n[i]>0:
						for k in range(int(n[i])): x.append([self.I.Items[i,0],self.I.Items[i,1]])
				ax = sns.kdeplot(np.array(x)[:,0], np.array(x)[:,1], shade=True, shade_lowest=False, alpha = 0.4, cmap=cmaps[cat],kernel='gau')
			
			# Scatter
			for i in range(self.I.totalNumberOfItems): 
				color = colors[self.I.ItemsClass[i]]
				if n[i]>=1:
					v = 0.4+ n[i]/np.max(n)*0.4
					c = (1,0,0.0,v)
					s = 2+n[i]/np.max(n)*40
					marker = 'o'
				else:
					color = (0,0,0,0.1)
					v = 0.1
					s = 10
					marker = 'x'
				ax.scatter(self.I.Items[i,0], self.I.Items[i,1], marker=marker, c=color,s=s,alpha=v)	
		
		# Final user position as a circle
		for i in range(len(self.U.Users[:,1])):
			ax.scatter(self.U.Users[i,0], self.U.Users[i,1], marker='+', c='k',s=20, alpha = 0.8 )
		
		# User drift
		if drift:
			for i in range(len(self.U.Users[:,1])):
				for j in range(len(self.U.X[i])-1):
					if self.U.X[i][j+1]!=0 and self.U.Y[i][j+1]!=0:
						ax.plot([self.U.X[i][j], self.U.X[i][j+1]], [self.U.Y[i][j], self.U.Y[i][j+1]], 'k-', lw=1, alpha =0.4)

		ax.set_xlabel(self.algorithm)
		ax.set_aspect('equal', adjustable='box')
		ax.set_xlim([-1.1,1.1])
		ax.set_ylim([-1.1,1.1])
		for tick in ax.xaxis.get_major_ticks():
			tick.label.set_fontsize(14)
		for tick in ax.yaxis.get_major_ticks():
			tick.label.set_fontsize(14) 
		matplotlib.pyplot.tight_layout()
		matplotlib.pyplot.savefig(self.outfolder + "/" + output)
		if not storeOnly: matplotlib.pyplot.show()
 
	def showSettings(self):
		""" A simple function to print most of the attributes of the class.

		"""

		variables = [key for key in self.__dict__.keys() if (type(self.__dict__[key]) is str or type(self.__dict__[key]) is float or type(self.__dict__[key]) is int or type(self.__dict__[key]) is list and len(self.__dict__[key])<10)]
		old = self.__dict__
		Json={ key: old[key] for key in variables }
		print(json.dumps(Json, sort_keys=True, indent=4))

	def initWithSettings(self, settings):
		
		# Simulation inits (not taken from the interface)
		self.AnaylysisInteractionData = []  # Holder for results/data
		self.D = []  # Distance matrix |Users|x|Items| between items and users
		self.SalesHistory = []  # User-item interaction matrix |Users|x|Items|7......7
		
		
		# Simulation inits taken from the interface
		printj("Initialize simulation class...")
		#sim.gallery = gallery 
		self.outfolder = settings["outfolder"]
		self.seed = int(settings["seed"])
		self.n = int(settings["Number of recommended articles per day"])
		self.algorithms = ['Control'] + settings["Recommender algorithms"].split(",")
		self.diversityMetrics = {}  # Holder for diversity metrics (means + std)
		for algorithm in self.algorithms:
			self.diversityMetrics.update({algorithm:{}})
			for key in ["EPC", "EPCstd",'ILD',"Gini", "EFD", "EPD", "EILD", 'ILDstd', "EFDstd", "EPDstd", "EILDstd"]:
				self.diversityMetrics[algorithm].update({key:[]})
		
			
		# The totalNumberOfIterations controls the amount of
		# items that will be generated. We first need to run a Control period for
		# iterarionsPerRecommender iterations, on different items than during the 
		# recommendation period, as such the total amount of iterations is doubled.
		self.totalNumberOfIterations = int(settings["Days"])*2 

		printj("Initialize users/items classes...")
		U = Users()
		I = Items()

		U.delta = float(settings["Recommender salience"])
		U.totalNumberOfUsers = int(settings["Number of active users per day"])
		U.seed = int(settings["seed"])
		U.Lambda = float(settings["Reading focus"])
		U.meanSessionSize = int(settings["Average read articles per day"])

		I.seed = int(settings["seed"])
		I.topicsFrequency = settings["Overall topic weights"]
		I.topicsSalience = settings["Overall topic prominence"]
		I.numberOfNewItemsPI = int(settings["Number of published articles per day"])

		I.generatePopulation(sim.totalNumberOfIterations)
		U.generatePopulation()
			
		printj("Create simulation instance...")
		self.U = copy.deepcopy(U)
		self.I = copy.deepcopy(I)
		
		self.D =  euclideanDistance(self.U.Users, self.I.Items)
		self.SalesHistory = np.zeros([self.U.totalNumberOfUsers,self.I.totalNumberOfItems]) 

		printj("Create recommendations instance...")
		self.Rec = Recommendations()
		self.Rec.U = copy.deepcopy(U)
		self.Rec.I = copy.deepcopy(U)
		self.Rec.n = int(settings["Number of recommended articles per day"])
	

if __name__ == '__main__':
	app = QApplication([])
	sim = SimulationGUI()
	sim.show()
	sys.exit(app.exec_()) 

	  
