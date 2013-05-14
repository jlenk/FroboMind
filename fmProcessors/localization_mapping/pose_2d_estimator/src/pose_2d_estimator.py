#!/usr/bin/env python
#*****************************************************************************
# Pose 2D Estimator Library
# Copyright (c) 2013, Kjeld Jensen <kjeld@frobomind.org>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright
#      notice, this list of conditions and the following disclaimer in the
#      documentation and/or other materials provided with the distribution.
#    * Neither the name FroboMind nor the
#      names of its contributors may be used to endorse or promote products
#      derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#*****************************************************************************
"""
This file contains a 2D pose estimator library designed for field robots.

A pose defines the position and orientation of a shape in world space
(or the parent coordinate space). In this implementation the pose describes
the robot lateral (2D) position in a geographical coordinate plane.

The pose is estimated based on sensor inputs from:
	Robot odometry feedback:
		Wheel encoders (typically fused with a gyro)
	Absolute position sensor:
		Real Time Kinematic GPS (RTK-GPS)
	Absolute orientation sensor:
		Attitude and heading reference system (AHRS)

Each sensor input is validated and filtered, and the actual variance is
estimated. This is based on generic and parameterized knowledge about
the field robot and sensor types.

An Extended Kalman Filter (EKF) then uses the robot odometry feedback as
system input (prediction) and the GNSS and AHRS information as measurement
inputs (correction).

The library is expected to be ported to C++ for performance optimations
but during development and test everything will be written in Python.

Revision
2013-04-25 KJ First version
"""
# imports
import numpy as np
from math import sqrt, pi, sin, cos, acos
from numpy import matrix, array, linalg, mat

# defines
buffer_initial_size_gnss = 200
buffer_initial_size_imu = 100
buffer_initial_size_odo = 100

class pose_2d_preprocessor():
	def __init__(self, max_speed):
		self.deg_to_rad = pi/180.0
		self.rad_to_deg = 180.0/pi
		self.max_speed = max_speed
		self.gnss = []
		self.gnss_buffer_time = 2 # [s]
		self.gnss_measurement_interval = -1 # [s]
		self.gnss_buffer_size = buffer_initial_size_gnss
		self.imu = []
		self.imu_buffer_time = 2 # [s]
		self.imu_measurement_interval = -1 # [s]
		self.imu_buffer_size = buffer_initial_size_imu
		self.odo = []
		self.odo_buffer_time = 2 # [s]
		self.odo_measurement_interval = -1 # [s]
		self.odo_buffer_size = buffer_initial_size_odo
	
	def validate_new_gnss_position(self, time_stamp, easting, northing):
		error = 0
		if self.gnss != []:

			### !!!!! THIS IS TEMPORARILY DISABLED UNTIL ROSBAGS WITH CORRECT time_recv DATA HAVE BEEN RECORDED.
			# dtime = time_stamp - self.gnss[-1][0]
			dtime = 0.200
			ddist = sqrt((easting - self.gnss[-1][2])**2 + (northing - self.gnss[-1][3])**2)
			max_dist = self.max_speed *dtime
			if ddist > max_dist: # if distance larger than possible when driving at maximum speed
				error = 1
				print "  GNSS position error at time stamp: %.3f: E%.3f, N%.3f" % (time_stamp, easting, northing)
		return error

	def estimate_orientation_from_gnss_positions (self):
		err = True
		yaw = 0.0
		buflen = len (self.gnss)
		if buflen >= 2:
			if self.gnss[-1][1] == 4: # if latest position is based on a fixed solution
				i = 1
				size = 0
				fix = 1
				E = 2
				N = 3
				while i<buflen and size < 0.25:
					i += 1
					if self.gnss[-i][fix] == 4: 
						size = sqrt ((self.gnss[-1][E]- self.gnss[-i][E])**2 + (self.gnss[-1][N]- self.gnss[-i][N])**2)
				if size >= 0.25: # if we found two coordinates at the required distance
					err = False
				
					# calc angle between gnss coordinate vector and northing axis
					northing_axis_vector_len = self.gnss[-1][N] - self.gnss[-i][N]
					gnss_coord_vector_len = size
					theta = acos(northing_axis_vector_len/gnss_coord_vector_len)
	
					# handle special case for the 2. and 3. quadrant
					if self.gnss[-i][E] > self.gnss[-1][E]:
						theta = 2.0*pi - theta
					#print theta*180/pi, i, size, self.gnss[-1][E]- self.gnss[-i][E], self.gnss[-1][N]- self.gnss[-i][N],self.gnss[-1][E],self.gnss[-1][N],self.gnss[-i][E],self.gnss[-i][N]
					yaw = theta

		return (err, yaw)
	

	def add_gnss_measurement (self, time_stamp, easting, northing, solution):
		err = True
		if solution > 0: # if satellite fix
			if not self.validate_new_gnss_position(time_stamp, easting, northing):
				self.gnss.append([time_stamp, solution, easting, northing])
				err = False
				if len(self.gnss) > self.gnss_buffer_size: # trim buffer length to size
					self.gnss.pop(0)
				elif len(self.gnss) == 50 and self.gnss_measurement_interval == -1: # update buffer size based on gnss update interval
					self.gnss_measurement_interval = (self.gnss[-1][0] - self.gnss[0][0])/50.0
					print "  Estimated GNSS measurement interval: %.3fs" % (self.gnss_measurement_interval)
					self.gnss_buffer_size = self.gnss_buffer_time / self.gnss_measurement_interval
		if err:
			self.gnss = []
		return err

	def add_imu_measurement(self, time_stamp, yaw_rate, yaw_orientation):
		self.imu.append([time_stamp, yaw_rate, yaw_orientation])
		if len(self.imu) > self.imu_buffer_size: # trim buffer length to size
			self.imu.pop(0)
		elif len(self.imu) == 50: # update buffer size based on gnss update interval
			self.imu_measurement_interval = (self.imu[-1][0] - self.imu[0][0])/50.0
			print "  Estimated IMU measurement interval: %.3fs" % (self.imu_measurement_interval)
			self.imu_buffer_size = self.imu_buffer_time / self.imu_measurement_interval
			while len(self.imu) > self.imu_buffer_size:
				self.imu.pop(0)

	def add_odometry(self, time_stamp, delta_dist, delta_angle):
		self.odo.append([time_stamp, delta_dist, delta_angle])
		if len(self.odo) > self.odo_buffer_size: # trim buffer length to size
			self.odo.pop(0)
		elif len(self.odo) == 50: # update buffer size based on gnss update interval
			self.odo_measurement_interval = (self.odo[-1][0] - self.odo[0][0])/50.0
			print "  Estimated odometry update interval: %.3fs" % (self.odo_measurement_interval)
			self.odo_buffer_size = self.odo_buffer_time / self.odo_measurement_interval
			while len(self.odo) > self.odo_buffer_size:
				self.odo.pop(0)

	def estimate_variance_gnss(self):
		# estimate speed
		# use known speed to increase variance
		std_dev = 20000000.0
		if len(self.gnss) > 0:
			if self.gnss[-1][1] == 4: # rtk fixed solution
				std_dev = 0.02
			elif self.gnss[-1][1] == 5: # rtk float solution
				std_dev = 2.0
			elif self.gnss[-1][1] == 2: # dgps solution
				std_dev = 7.0
			elif self.gnss[-1][1] == 1: # sps solution
				std_dev = 15.0
		return std_dev**2

	def estimate_yaw(self):
		pass

	def remove_old_measurements (self):
		pass

class pose_2d_ekf():
	def __init__(self):
		self.prevX = self.set_initial_guess([0.0, 0.0, 0.0])
		self.prevCov = np.matrix([[100000000**2.0,0.0,0.0],[0.,100000000**2,0.0], \
			[0.0,0.0,2.0*pi]]) # high variance for the initial guess 
		self.Q = np.identity(3)
		self.Hgnss = np.matrix([[1., 0., 0.,],[0., 1., 0.]]) # GNSS observation matrix
		self.Hahrs = np.matrix([[0., 0., 0.,],[0., 0., 1.]]) # AHRS observation matrix

	def set_initial_guess (self, x):
		self.prevX = np.matrix(x)

	def system_update (self, delta_dist, var_dist, delta_angle, var_angle):
		u = [delta_dist, delta_angle]

		# predicted (A priori) state estimate: X-[t] = X[t-1] + u[t]
		priX = self.f(self.prevX, u)

		# predicted (A priori) error covariance estimate: P-[t] = P[t-1] + Q
		self.Q = self.Q + np.matrix([[delta_dist*var_dist, 0.0, 0.0], \
			[0.0, delta_dist*var_dist, 0.0], \
			[0.0, 0.0, delta_angle/(2*pi)*var_angle]])
		Gm = self.G(self.prevX, u)
		priCov = Gm*self.prevCov*Gm.T + self.Q 

		# housekeeping
		self.prevX = priX # advance to next update step
		self.prevCov = priCov
		return array(self.prevX)[0]

	def measurement_update_pos (self, pos, var_pos):
		# Compute Kalman gain: K[t] = P-[t]/(P-[t] + R)
		K = self.prevCov*self.Hgnss.T*linalg.inv(self.Hgnss*self.prevCov*self.Hgnss.T + self.R(var_pos))
		#print 'R', self.R(var_pos)
		#print 'k', K

		# updated (A posteriori) estimate with measurement z[t]: X[t] = X-[t] + K[t]*(z[t] - X-[t])
		prev_pos = [array(self.prevX)[0][0], array(self.prevX)[0][1]] # A priori position
		#print 'prev_pos', prev_pos
		
		y = np.matrix(pos).T - np.matrix(prev_pos).T # measurement residual
		#print 'y', y

		postX = self.prevX + (K*y).T # updated state estimate
		#print 'postX', postX

		# updated (A posteriori) error covariance: P[t] = (1 - K[t])*P-[t]
		postCov = (mat(np.identity(3))-K*self.Hgnss)*self.prevCov

		# housekeeping
		self.Q = np.identity(3) # reset the process noise covariance matrix
		self.prevX = postX # advance to next update step
		self.prevCov = postCov # save A posteriori error variance estimate
		return array(self.prevX)[0]

	def measurement_update_yaw (self, yaw, var_yaw):
		self.prevX[2][2] = yaw
		return array(self.prevX)[0]
		pass

	def R (self, var_pos): # measurement error covariance matrix
		return np.matrix([[var_pos, 0.],[0., var_pos]])

	def f (self, x, u): # predict state
		# x is the state vector at timestep k: [X, Y, theta].T
		# u is the system input vector at timestep k: [delta_dist, delta_angle].T
		x = array(x)[0]
		theta = x[2]
		dTheta = u[1]
		l1 = [x[0]+u[0]*cos(theta+dTheta/2.),x[1]+u[0]*sin(theta+dTheta/2.),theta+dTheta]
		return np.matrix(l1)

	def G (self, x, u): # system error covariance matrix
		# x is the state vector at timestep k: [X, Y, theta].T
		# u is the system input vector at timestep k: [delta_dist, delta_angle].T
		x = array(x)[0]
		theta = x[2]
		dTheta = u[1]
		l1 = [1., 0., -u[0]*sin(theta+dTheta/2.)]
		l2 = [0., 1., u[0]*cos(theta+dTheta/2.)]
		l3 = [0., 0., 1.]
		return (np.matrix([l1, l2, l3]))

