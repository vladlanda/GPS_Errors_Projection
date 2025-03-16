
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import re
# import cartopy.crs as ccrs
import pandas as pd
import subprocess
import os
from ftplib import FTP_TLS
# import platform
import cdflib
import glob
from pathlib import Path
import io
import datetime
from numpy.lib.arraypad import pad

from tqdm import tqdm
import time,threading,logging
import requests
# import requests_gssapi as requests

from typing import List

from io import BytesIO
from atomicwrites import atomic_write
import hatanaka
from multiprocessing import Pool, cpu_count


import logging
logging.basicConfig(level=logging.INFO)

# from DMD.utilities import algorithms_dmd
import DMD.algorithms_dmd as dmd

AGENCIES : List[str] = ['IGS','JPL','ESA','COD']
OLD_AGENCIES_PRIORITY : List[str] = ['igs','jpl','upc','igr','jpr','upr']
RESOLUTION : List[str]  = ['02H','01H']
SOLUTION_TYPES : List[str]  = ['FIN','RAP']#,'ULT']
CAMPAINGE : List[str]  = 'OPS'
BASE_URL = 'https://cddis.nasa.gov/archive/gnss/products/ionex'
RMS_MAP_DIM = (13,71,73)
CODE_PREDICTED_NAMES = ['c1p','c2p']

MAX_PROCESSES = cpu_count() // 2
VERIFY_REST_SECURITY = True

#https://notebook.community/daniestevez/jupyter_notebooks/IONEX
#https://cddis.nasa.gov/Data_and_Derived_Products/GNSS/atmospheric_products.html

def ionex_filename_to_date(filename):
    if os.sep in filename: 
        filename = filename.split(os.sep)[-1]
    # a = re.findall(r'\d+', filename)
    a = re.findall(r'\d{2,}', filename)
    day_number = a[0][:-1]
    year = '20'+a[1]
    # print(day_number,year,a)
    return day_number_to_date(day_number,year)

def day_number_to_date(day_number,year):
    day_number = str(day_number)
    year = str(year)
    # print(day_number,year)
    res = datetime.datetime.strptime(year + "-" + day_number, "%Y-%j")
    return res

def date_to_year_day_number(year,month,day):
	today = datetime.date(year, month, day)
	return int(today.strftime('%j'))

def time_to_index_day_number(hours,minutes,step_in_minutes):
	h_step = int(60 / step_in_minutes)
	h = hours * h_step
	m = int(minutes / step_in_minutes)
	return int(h+m)

def index_day_number_to_time(index,step_in_minutes):
	h_step = 60 / step_in_minutes
	h = int(index / h_step) % 24
	m = int((index % h_step) * step_in_minutes)

	return h,m

def datetime_to_gpsweekday(date):
    zero_epoch = datetime.datetime(1980, 1, 6)
    
    week = (date - zero_epoch).days // 7
    day = (date - zero_epoch).days % 7

    return week,day

def date_to_doy(date):
    dt = date - datetime.datetime(year=date.year,month=1,day=1)
    return dt.days+1

class IONEXv2(object):

	def __init__(self, save_directory, n_prior_days = 120):
		self.directory = save_directory
		self.n_prior_days = n_prior_days

    ##################################################
    #      #
    ##################################################

	def _get_prioritized_list_of_products(self,date):

		names = []
		zip_names = []

		doy = '{:03d}'.format(date_to_doy(date))
		'''Priority #3-6'''
		for temporal_resolution in RESOLUTION:
			for solution in SOLUTION_TYPES:
				for agency in AGENCIES:
						file_name = f'{agency.upper()}0{CAMPAINGE}{solution}_{date.year}{doy}0000_01D_{temporal_resolution}_GIM.INX'
						unzipped_name = f'FORDMDUSE_{date.year}{doy}0000_01D_GIM.INX'
						# print(agency.upper(),temporal_resolution)
						names.append(file_name)
						# names.append(unzipped_name)
						zip_names.append(f'{file_name}.gz')

		for agency in OLD_AGENCIES_PRIORITY:
			file_name = '{}g{:03d}0.{:02d}i'.format(agency, date_to_doy(date), date.year % 100)
			names.append(file_name)
			# names.append(unzipped_name)
			zip_names.append(f'{file_name}.Z')	


		return zip_names,names
	

	def predict_dmd_map(self,current_date,check_priority_files = True,debug = False):
		
		predicted_code_files = []
		for _name in CODE_PREDICTED_NAMES:
			logging.info(f'Checking {_name.upper()} for {current_date}')
			cod = self._check_cod_avilability(current_date,_name=_name)
			if not cod:
				logging.info(f'Downloading {_name.upper()}...')
				cod = self.download_cod(current_date,_name)
				# if _name == 'c1p': cod = None
				# if not cod:
					# logging.info('Download Failed!')
					# required_cod_file = self._get_cod_file_name(current_date,_name=_name)
					# raise Exception(f'{os.path.basename(required_cod_file)} CAN\'T BE DOWNLOADED!')
			predicted_code_files.append(cod)
			logging.info(f'{_name.upper()} files found: {cod}')

		# logging.info(f'Checking C1P for {current_date}')
		# c2p = self._check_cod_avilability(current_date,_name='c2p')
		# if not c2p:
		# 	logging.info('Downloading C1P...')
		# 	c2p = self.download_c1p(current_date)
		# 	if not c2p:
		# 		logging.info('Download Failed!')
		# 		required_c2p_file = self._get_c1p_file_name(current_date)
		# 		raise Exception(f'{os.path.basename(required_c2p_file)} CAN\'T BE DOWNLOADED!')

		delayed_date_range = [current_date - datetime.timedelta(days=1) * i for i in range(1,self.n_prior_days+1)]
		missing_dates = []
		updated_dates = []
		logging.info(f'Checking RMS products from {delayed_date_range[0]} to {delayed_date_range[-1]}')

		for delayed_date in delayed_date_range:
			rms_product = self._check_rms_product_availability(delayed_date)
			if not rms_product:
				missing_dates.append(delayed_date)
			elif check_priority_files:
				_,priorotize_products = self._get_prioritized_list_of_products(delayed_date)
				rms_product_name = rms_product.split(os.sep)[-1]
				priority_index = priorotize_products.index(rms_product_name)
				if priority_index > 0:
					updated_dates.append(delayed_date)


		logging.info(f'Found {len(missing_dates)} missing RMS products!')
		if len(missing_dates) > 0:
			logging.info('Downloading missing RMS products...')
			results = self.download_ionex_by_date_list(missing_dates)
			logging.info(f'Done Downloading {len(results)} RMS products!')
		elif len(updated_dates) > 0:
			logging.info('Prioritized RMS product might be available, trying to download....')
			results = self.download_ionex_by_date_list(updated_dates)
			logging.info(f'Done Downloading {len(results)} prioritized RMS products!')

		list_of_rms_products = [self._check_rms_product_availability(delayed_date) for delayed_date in delayed_date_range] 

		# TODO implement dmd prediction c1p + c2p

		n_pred_days = 1
		for p in list_of_rms_products:
			if not p is None: break
			n_pred_days += 1

		logging.info(f'Executing DMD...,#{n_pred_days} days prediction')
		rms_maps = self.get_numpy_rmsmaps(list_of_rms_products)
		pred_maps = dmd.DMD_prediction(rms_maps,n_pred_days=n_pred_days)
		# print(predicted_code_files)
		logging.info(f'Saving files...')

		created_files = []
		for cod_file,cod_name in zip(predicted_code_files,CODE_PREDICTED_NAMES):
			if cod_file is None: continue
			dmd_file = dmd_rms_ionex(cod_file_path=cod_file,
				 		  dmd_predicted_maps=pred_maps,
						  _replace=cod_name,
						#   _save_location = os.path.join(self.directory,'..','products'))
						_save_location = os.path.join(self.directory))
			created_files.append(dmd_file)
		logging.info(f'Done!')
		
		return created_files
	
	def get_numpy_rmsmaps(self,files_path):

		result = np.zeros((0,*RMS_MAP_DIM))
		for file_name in files_path:
			try:
				np_tmap = np.array(self._get_rmsmaps(file_name))
				# print(file_name,np.max(np_tmap))
				if np.max(np_tmap) > 998:
					raise FileNotFoundError("Values exiding 999!")
			except Exception as e:
				# print(e,file_name,'Appending previous file')
				if result.shape[0] > 0:
					result = np.concatenate((np.expand_dims(result[0],0),result))
				continue
			if np_tmap.shape[0] > 13:
				np_tmap = np_tmap[list(range(0,26,2)),:,:]
			np_tmap = np_tmap.reshape(1,*RMS_MAP_DIM)
			result = np.concatenate((np_tmap,result))

		return result
		
	def _get_rmsmaps(self,filename):
		with open(filename) as f:
			ionex = f.read()
			return [self._parse_rms(t) for t in ionex.split('START OF RMS MAP')[1:]]
		
	def _parse_rms(self,tecmap, exponent = -1):
		tecmap = re.split('.*END OF RMS MAP', tecmap)[0]
		return np.stack([np.fromstring(l, sep=' ') for l in re.split('.*LAT/LON1/LON2/DLON/H\\n',tecmap)[1:]])*10**exponent		
	
	def _check_cod_avilability(self,date,_name='c1p'):

		c1p_file = self._get_cod_file_name(date,_name)
		c1p_files = glob.glob(os.path.join(self.directory,f'{_name}*.*i'))
		c1p_file_names = [c1p for c1p in c1p_files if c1p_file in [os.path.basename(f) for f in c1p_files]]
		is_c1p_exist = len(c1p_file_names) == 1

		c1p = None if not is_c1p_exist else c1p_file_names[0]

		return c1p
	
	def _check_rms_product_availability(self,delayed_date):

		_,file_name_to_search = self._get_prioritized_list_of_products(delayed_date)
		all_existing_files = glob.glob(os.path.join(self.directory,'*'))
		all_existing_file_names = [os.path.basename(f) for f in all_existing_files]
		candidate_files = [os.path.join(self.directory,candidate) for candidate in file_name_to_search if candidate in all_existing_file_names]
		is_candidate_exit = len(candidate_files) >= 1

		rms_product = None if not is_candidate_exit else candidate_files[0]

		return rms_product
	
	def _get_cod_file_name(self,date,_name):
		return '{}g{:03d}0.{:02d}i'.format(f'{_name}', date_to_doy(date), date.year % 100)
	
	def _get_url_file_path(self,date,file_name):
			doy = '{:03d}'.format(date_to_doy(date))
			year = '{:04d}'.format(date.year)
			url = '{}/{}/{}/{}'.format(BASE_URL,year,doy,file_name)

			return url

	def _download_and_save_file(self,url,file_path):
		def download(url):
			# filename = url.split('/')[-1]
			
			response = requests.head(url,verify=VERIFY_REST_SECURITY)
			if response.status_code != 200:
				# raise Exception('HTTP error ' + str(response.status_code) +" "+ str(url))
				return None
			n_attepts = 3
			response = None
			for n in range(n_attepts):
				try:
					response = requests.get(url,verify=VERIFY_REST_SECURITY)
				except:
					# print(f'Error downloading {url}')
					pass
				if response: break
			if response is None: return None
			buf = BytesIO()
			for chunk in response.iter_content(chunk_size=1000):
					buf.write(chunk)
			return buf.getvalue()
		
		if os.path.isfile(file_path): return file_path
		data_zipped = download(url)
		if data_zipped is None: 
			
			return None

		ephem_bytes = hatanaka.decompress(data_zipped)
		with atomic_write(file_path, mode='wb', overwrite=True) as f:
			f.write(ephem_bytes)

		return file_path
	
	def download_cod(self,current_date,_name):

		for date in [current_date - datetime.timedelta(days=1) * i for i in range(1)]:

			file_name = self._get_cod_file_name(date,_name)
			zip_name = f'{file_name}.Z'

			url = self._get_url_file_path(date,zip_name)

			extracted_file_path = os.path.join(self.directory,file_name)
			os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)
			# print(date,url)
			cod = self._download_and_save_file(url,extracted_file_path)
			if cod:
				return cod
			
	def download_all_ionex_at_once(self, current_date, files_report = False,debug=False,run_async=False):

		dates_list = [current_date - datetime.timedelta(days=1) * i for i in range(self.n_prior_days)]

		files_to_download_dict = {}

		for date in dates_list:

			zip_names,file_names = self._get_prioritized_list_of_products(date)

			for zip_name,file_name in zip(zip_names,file_names):

				url = self._get_url_file_path(date,zip_name)
				
				extracted_file_path = os.path.join(self.directory,file_name)
				os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

				if requests.head(url,verify=VERIFY_REST_SECURITY).status_code == 200:
					files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
					break

				# if self._download_and_save_file(url,extracted_file_path):
					# break

		# TODO implement thread pool downloading
		print(files_to_download_dict)
		pass

	def download_ionex_by_date_list(self,dates_list,files_report = False,debug=False):

		files_to_download_dict = {}
		for date in dates_list:
			zip_names,file_names = self._get_prioritized_list_of_products(date)

			for zip_name,file_name in zip(zip_names,file_names):

				url = self._get_url_file_path(date,zip_name)
				
				extracted_file_path = os.path.join(self.directory,file_name)
				os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

				if requests.head(url,verify=VERIFY_REST_SECURITY).status_code == 200:
					files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
					break

				# if self._download_and_save_file(url,extracted_file_path):
					# break

		logging.info('Downloading Async...')
		urls_to_download = [value['url'] for value in files_to_download_dict.values()]
		pool = Pool(MAX_PROCESSES)
		results = pool.starmap(self._download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
		pool.close()
		pool.join()
		
		return results


class IONEX(object):

	def __init__(self, save_directory , centre = 'esa'):
		self.centre = centre
		self.directory = save_directory
	
	def parse_map(self,tecmap, exponent = -1):
		tecmap = re.split('.*END OF TEC MAP', tecmap)[0]
		return np.stack([np.fromstring(l, sep=' ') for l in re.split('.*LAT/LON1/LON2/DLON/H\\n',tecmap)[1:]])*10**exponent
	
	def parse_rms(self,tecmap, exponent = -1):
		tecmap = re.split('.*END OF RMS MAP', tecmap)[0]
		return np.stack([np.fromstring(l, sep=' ') for l in re.split('.*LAT/LON1/LON2/DLON/H\\n',tecmap)[1:]])*10**exponent

	def get_numpy_tecmaps(self,years_list,days_list):
		if not type(days_list) == list: days_list = [days_list]
		if not type(years_list) == list: years_list = [years_list]
		result = None
		file_names = []
		# for year in tqdm(years_list,desc="Year",position=0, leave=True):
		for year in years_list:
			for day in tqdm(days_list,desc="Year : {}, Days : ".format(year),position=0, leave=True):
				try:
					file_name = self.ionex_local_path(year,day)
					np_tmap = np.array(self.get_tecmaps(file_name))
					file_names.append(file_name)
				except Exception as e:
					print(e,file_name)
					continue
				if np_tmap.shape[0] > 13:
					np_tmap = np_tmap[list(range(0,26,2)),:,:]
				d,h,w = np_tmap.shape
				np_tmap = np_tmap.reshape(1,d,h,w)

				#print(np_tmap.shape)
				if result is None:
					result = np_tmap.copy()
				else:
					result = np.vstack((result,np_tmap))
				# print(result.shape)
		return result,file_names

	def get_numpy_rmsmaps(self,years_list,days_list):
		if not type(days_list) == list: days_list = [days_list]
		if not type(years_list) == list: years_list = [years_list]
		result = None
		file_names = []
		# for year in tqdm(years_list,desc="Year",position=0, leave=True):
		for year in years_list:
			for day in tqdm(days_list,desc="Year : {}, Days : ".format(year),position=0, leave=True):
				try:
					file_name = self.ionex_local_path(year,day)
					file_names.append(file_name)
					np_tmap = np.array(self.get_rmsmaps(file_name))
					# print(file_name,np.max(np_tmap))
					if np.max(np_tmap) > 998:
						raise FileNotFoundError("Values exiding 999!")
				except Exception as e:
					print(e,file_name,'Appending previous file : {}'.format(file_names[-2]))
					f_idx = 2
					while 1:
						try:
							file_name = file_names[-f_idx]
							np_tmap = np.array(self.get_rmsmaps(file_name))
							
							if np.max(np_tmap) > 9998:
								raise FileNotFoundError("Values exiding 999!")
							break
						except:
							print(e,file_name,'Appending previous file : {}'.format(file_name))
							f_idx+=1


					# file_names.append(file_name)
					# continue
				if np_tmap.shape[0] > 13:
					np_tmap = np_tmap[list(range(0,26,2)),:,:]
				# print(file_name)
				d,h,w = np_tmap.shape
				np_tmap = np_tmap.reshape(1,d,h,w)

				#print(np_tmap.shape)
				if result is None:
					result = np_tmap.copy()
				else:
					result = np.vstack((result,np_tmap))
				# print(result.shape)
		return result,file_names

	def get_tecmaps(self,filename):
		with open(filename) as f:
			ionex = f.read()
			return [self.parse_map(t) for t in ionex.split('START OF TEC MAP')[1:]]

	def get_rmsmaps(self,filename):
		with open(filename) as f:
			ionex = f.read()
			return [self.parse_rms(t) for t in ionex.split('START OF RMS MAP')[1:]]

	def get_tec(self,tecmap, lat, lon):
		i = round((87.5 - lat)*(tecmap.shape[0]-1)/(2*87.5))
		j = round((180 + lon)*(tecmap.shape[1]-1)/360)
		return tecmap[i,j]

	def ionex_filename(self,year, day, zipped = True):
		return '{}g{:03d}0.{:02d}i{}'.format(self.centre, day, year % 100, '.Z' if zipped else '')

	def ionex_ftp_path(self,year, day):
		"""
		'gps/products/ionex/2010/001/esag0010.10i.Z'
		"""
		return '/gps/products/ionex/{:04d}/{:03d}/{}'.format(year, day, self.ionex_filename(year, day))
		# return 'ftp://cddis.gsfc.nasa.gov/gps/products/ionex/{:04d}/{:03d}/{}'.format(year, day, self.ionex_filename(year, day, self.centre))

	def ionex_ftp_path_v2(self,year, day):
		"""
		'gps/products/ionex/2010/001/esag0010.10i.Z'
		"""
		return '/gps/products/ionex/{:04d}/{:03d}/{}'.format(year, day, self.ionex_filename(year, day))

	def ionex_local_path(self,year, day, zipped = False):
		return os.path.join(self.directory,str(year),self.ionex_filename(year, day, zipped))

	def create_dir_path(self,filename):
		if not os.path.exists(os.path.dirname(filename)):
			try:
				os.makedirs(os.path.dirname(filename))
			except OSError as exc: # Guard against race condition
				pass
	
	# def download_single_ionex(self,year,day,ftps,files_report = False,debug=False):
	def download_single_ionex(self,ftp_path,filename_zip,filename,files_report = False,debug=False):
		# y=year
		# d=day
		# ftp_path = self.ionex_ftp_path(y, d)

		# filename_zip = os.path.join(self.directory,str(y),'zip',self.ionex_filename(y, d))
		# filename = os.path.join(self.directory,str(y),self.ionex_filename(y, d))[:-2]

		self.create_dir_path(filename_zip)
		self.create_dir_path(filename)

		if not os.path.isfile(filename_zip) or os.path.getsize(filename_zip) < 1:
			ftps = FTP_TLS(host = 'gdc.cddis.eosdis.nasa.gov')
			ftps.login(user='anonymous', passwd='1234@gmail.com')
			ftps.prot_p()
			try:
				os.remove(filename_zip)
			except: pass
			# if debug : 
			logging.info('Downloading... : {}'.format(filename_zip))
			try:
				ftps.retrbinary("RETR " + ftp_path, open(filename_zip, 'wb').write)
			except OSError as ose:
				logging.info('OSError : {}, Another attempt!'.format(ose))
				ftps.retrbinary("RETR " + ftp_path, open(filename_zip, 'wb').write)
				pass
			except Exception as ex:
				logging.info('File Not Found {}: '.format(filename_zip),ex)
		else:
			if debug : logging.info('{} exist!'.format(filename_zip))

		if not os.path.isfile(filename):
			if debug : logging.info('Extracting... : {}, From : {}'.format(filename,filename_zip))
			try:
				subprocess.call(['7z', 'e', filename_zip,'-o'+os.path.dirname(filename)])
			except Exception as ex:
				logging.info('Couldn\'t Extract File : {}'.format(ex))
			
			# if platform.system() == 'Windows':
			# 	subprocess.call(['7z', 'e', filename_zip,'-o'+os.path.dirname(filename)])
			# else:
			# 	subprocess.call(['gzip', '-d', filename])
		else:
			if debug : logging.info('{} exist!'.format(filename))


		ftps.close()



	def download_ionex(self, year, day, files_report = False,debug=False,run_async=False):
		if not type(year) == list:
			year = [year]
		if not type(day) == list:
			day = [day]




		if run_async:
			format = "%(asctime)s: %(message)s"
			logging.basicConfig(format=format, level=logging.INFO,
					datefmt="%H:%M:%S")
			thread_batch = 5
			threads = []
			for y in year:
				for d in day:
					
					# x = threading.Thread(target=self.download_single_ionex, args=(y,d,ftps,files_report,debug,))

					# y=year
					# d=day
					ftp_path = self.ionex_ftp_path(y, d)
					filename_zip = os.path.join(self.directory,str(y),'zip',self.ionex_filename(y, d))
					filename = os.path.join(self.directory,str(y),self.ionex_filename(y, d))[:-2]

					x = threading.Thread(target=self.download_single_ionex, args=(ftp_path,filename_zip,filename,files_report,debug,))
					x.start()
					threads.append(x)
					# self.download_single_ionex(y,d,files_report,debug)

					if len(threads) > thread_batch:
						for t in threads:
							t.join()
						logging.info('Batch of {} threads is DONE! Year {}, day {}'.format(thread_batch,y,d))
						threads = []
					



			return

		ftps = FTP_TLS(host = 'gdc.cddis.eosdis.nasa.gov')
		ftps.login(user='anonymous', passwd='1234@gmail.com')
		ftps.prot_p()

		files_dict = {'file_path':[],'file_size':[]}

		for y in year:
			for d in day:
				ftp_path = self.ionex_ftp_path(y, d)

				filename_zip = os.path.join(self.directory,str(y),'zip',self.ionex_filename(y, d))
				filename = os.path.join(self.directory,str(y),self.ionex_filename(y, d))[:-2]

				self.create_dir_path(filename_zip)
				self.create_dir_path(filename)

				# print(ftps.size(ftp_path))


				if files_report:
					f_server_size = -1
					try:
						if debug: print(ftp_path)
						f_server_size = ftps.size(ftp_path)
					except Exception as e:
						print('----',e)
						pass
					if(f_server_size < 1):
						print('ERROR : NO SUCH FILE ON SERVER {}'.format(filename_zip))
					
					files_dict['file_path'].append(filename_zip)
					files_dict['file_size'].append(f_server_size)


				if not os.path.isfile(filename_zip) or os.path.getsize(filename_zip) < 1:
					try:
						os.remove(filename_zip)
					except: pass
					if debug : print('Downloading... : ',filename_zip)
					try:
						ftps.retrbinary("RETR " + ftp_path, open(filename_zip, 'wb').write)
					except OSError as ose:
						print('OSError : {}, Another attempt!'.format(ose))
						ftps.retrbinary("RETR " + ftp_path, open(filename_zip, 'wb').write)
						pass
					except Exception as ex:
						print('File Not Found {}: '.format(filename_zip),ex)
				else:
					if debug : print(filename_zip,' exist!')

				if not os.path.isfile(filename):
					if debug : print('Extracting... : ',filename,', From : ',filename_zip)
					try:
						subprocess.call(['7z', 'e', filename_zip,'-o'+os.path.dirname(filename)])
					except Exception as ex:
						print('Couldn\'t Extract File : ',ex)
					
					# if platform.system() == 'Windows':
					# 	subprocess.call(['7z', 'e', filename_zip,'-o'+os.path.dirname(filename)])
					# else:
					# 	subprocess.call(['gzip', '-d', filename])
				else:
					if debug : print(filename,' exist!')

		ftps.close()


		if files_report:
			df = pd.DataFrame.from_dict(files_dict)
			csv_report_file = os.path.join(self.directory,'files_report.csv')
			df.to_csv(csv_report_file)

		if debug : print('DONE!')
		
	# def plot_tec_map(self,tecmap):
	# 	proj = ccrs.PlateCarree()
	# 	f, ax = plt.subplots(1, 1, subplot_kw=dict(projection=proj))
	# 	ax.coastlines()
	# 	h = plt.imshow(tecmap, cmap='viridis', vmin=0, vmax=100, extent = (-180, 180, -87.5, 87.5), transform=proj)
	# 	plt.title('VTEC map')
	# 	divider = make_axes_locatable(ax)
	# 	ax_cb = divider.new_horizontal(size='5%', pad=0.1, axes_class=plt.Axes)

	# 	f.add_axes(ax_cb)
	# 	cb = plt.colorbar(h, cax=ax_cb)
	# 	plt.rc('text', usetex=True)
	# 	cb.set_label('TECU ($10^{16} \\mathrm{el}/\\mathrm{m}^2$)')	
		

class IONEX_CDF(object):
    
	def __init__(self,save_directory):
    	
		self.directory = save_directory

	def get_numpy_tecmaps(self,years_list):
    		
		days_array = []
		
		for year in years_list:
    	
			fpath = os.path.join(self.directory,str(year),'*.cdf')
			cdf_files_list = glob.glob(fpath)

			
			cdf_files_list.sort()
			for file in cdf_files_list:#,desc="CDF {} : ".format(fpath)):
				# print(file)
				cdf = cdflib.CDF(file)
				# print(cdf.varget('lat'),cdf.varget('lon'))


				days_array.append(cdf.varget('tecUQR'))
				
			
		days_array = np.array(days_array)
		return days_array



def map_matrix2string_ionex(matrix,inonex_map_columns=16):
    n=inonex_map_columns
    test_map_str = [["   "+'   '.join(map(str, arr[i:i + n])) for i in range(0, len(arr), n)] for arr in matrix]
    test_map_str = ['\n'.join(map(str, l)) for l in test_map_str]
    return test_map_str

def dmd_ionex(c1p_file_path,dmd_predicted_maps,_replace='c1p',_replace_with='dmd',debug=False):
    data = ''
    file_path = c1p_file_path
    maps = dmd_predicted_maps[0]
    with open(file_path,'r') as f:
        line  = f.readline()
        map_count = 0
        lat_count = 0
        test_map_str = map_matrix2string_ionex(maps[map_count])
        while line:
            
            data += line
            if "LAT/LON1/LON2/DLON/H" in line:
                try:
                    for _ in range(5):
                        line  = f.readline()
                    data += test_map_str[lat_count]+"\n"
                    lat_count+=1
                except IndexError as ie:
                    if debug: print('ERROR : ',map_count,lat_count,line)
                    pass
            if "END OF TEC MAP" in line:
                map_count+=1
                lat_count=0
                try:
                    test_map_str = map_matrix2string_ionex(maps[map_count])
                except:
                     if debug: print('ERROR : ',map_count,maps.shape)

            line  = f.readline()
            if "START OF RMS MAP" in line:
                break
        while line:
            data += line
            line  = f.readline()

    dmd_file = file_path.replace(_replace,_replace_with)

    if debug : print(dmd_file,os.path.dirname(dmd_file))
    Path(os.path.dirname(dmd_file)).mkdir(parents=True, exist_ok=True)
    with open(dmd_file,'w') as f:
        f.write(data)
	
def start_of_map_string(map_index,n_chars=80):

    result = "{}"+" "*54
    result = result.format(map_index+1)+"START OF RMS MAP    "
    result = " "*(n_chars-len(result))+result+"\n"

    return result

def end_of_map_string(map_index,n_chars=80):

    result = "{}"+" "*54
    result = result.format(map_index+1)+"END OF RMS MAP      "
    result = " "*(n_chars-len(result))+result+"\n"

    return result

def epoch_of_current_map_string(filename,map_index,n_chars=80):

    ionex_date = ionex_filename_to_date(filename)

    hour_number = map_index*2

    hour = "{}".format(hour_number%24)
    hour = " "*(6-len(hour))+hour
    
    hour_padding = (" "*5+"0")
    hour_padding += hour_padding

    days_to_advance = int(hour_number//24)
    ionex_date += datetime.timedelta(days=days_to_advance)

    #https://stackoverflow.com/questions/904928/python-strftime-date-without-leading-0
    year  = ionex_date.strftime("  %Y")
    month = ionex_date.strftime("%#m")
    day   = ionex_date.strftime("%#d")

    month = " "*(6-len(month))+month
    day = " "*(6-len(day))+day

    text = "EPOCH OF CURRENT MAP\n"

    prefix = year+month+day+hour+hour_padding

    result = prefix+" "*(n_chars+1-len(prefix)-len(text))+text

    return result

def map_latitude_string(latitude_index):

    posfix = "-180.0 180.0   5.0 450.0                            LAT/LON1/LON2/DLON/H\n"
    lat = "{}".format(87.5 - latitude_index * 2.5)
    lat = " "*(8-len(lat))+lat
    result = lat+posfix
    return result

def shrink_ionex_to_13_maps(ionex_lines_content):
    START_OF_MAP = "START OF TEC MAP"
    END_OF_MAP = "END OF TEC MAP"
    # test if shrinking required
    ionex_content = "".join(ionex_lines_content)
    n_maps = len(ionex_content.split(START_OF_MAP)[1:])
    if n_maps <= 13 : return ionex_lines_content

    header_to_replace = {'INTERVAL':'7200','# OF MAPS IN FILE':'13'}


    start_map_indecies_to_replace = {i+1:0 for i in range(n_maps-1,0,-1)}
    end_map_indecies_to_replace = {i+1:0 for i in range(n_maps-1,0,-1)}

    map_count=1
    end_map_count = 1



    for i,line in enumerate(ionex_lines_content):

        for key,val in header_to_replace.items():

            if key in line:
                # print(line)
                # print(re.sub('\d+', val, line))
                ionex_lines_content[i] = re.sub('\d+', val, line)

        if START_OF_MAP in line:
            # print(i,line)
            start_map_indecies_to_replace[map_count] = i
            map_count+=1

        if END_OF_MAP in line:
            # print(i,line)
            end_map_indecies_to_replace[end_map_count] = i
            end_map_count+=1

    #replace START OF TEC MAP indecies
    for key,index in start_map_indecies_to_replace.items():

        new_key = key//2+1
        new_index = start_map_indecies_to_replace[new_key]

        ionex_lines_content[index] = ionex_lines_content[new_index]

    for key,index in end_map_indecies_to_replace.items():

        new_key = key//2+1
        new_index = end_map_indecies_to_replace[new_key]

        ionex_lines_content[index] = ionex_lines_content[new_index]

    ionex_content = "".join(ionex_lines_content)

    split_start_maps = ionex_content.split(START_OF_MAP)
    header = split_start_maps[0]

    maps_string_list = split_start_maps[1:]
    map_indecies_to_select = list(range(0,26,2))
    shrinked_map_list = [maps_string_list[i] for i in map_indecies_to_select]

    shrinked_content = header+START_OF_MAP+START_OF_MAP.join(shrinked_map_list)

    list_content = [l+"\n" for l in shrinked_content.split('\n')]

    return list_content

def dmd_rms_ionex(cod_file_path,dmd_predicted_maps,_save_location,_replace='c1p',_replace_with='dmd_rms',debug=False):
    data = ''
    _replace_with = f'{_replace}_{_replace_with}'

    file_path = cod_file_path
    maps = dmd_predicted_maps
    # if _replace == 'c1p':
        # maps = dmd_predicted_maps[:12]
    # elif _replace == 'c2p':
        # maps = dmd_predicted_maps[12:]

    for map_index,_map in enumerate(maps):

        data += start_of_map_string(map_index)
        data += epoch_of_current_map_string(cod_file_path,map_index)

        maps_string = map_matrix2string_ionex(_map)
        for lat_index,map_array in enumerate(_map):

            data += map_latitude_string(lat_index)
            data += maps_string[lat_index]+'\n'
        
        data += end_of_map_string(map_index)

    with io.open(file_path,'r',newline='\n') as f:
        ionex_lines_content = f.readlines()

    content = shrink_ionex_to_13_maps(ionex_lines_content)
    # with io.open(file_path,'r',newline='\n') as f:
    #     lines_content = f.readlines()

    lines_content = content
    lines_content.insert(-1,data)
    lines_content = "".join(lines_content)

    dmd_file = file_path.replace(_replace,_replace_with)
    dmd_file = os.path.join(_save_location,os.path.basename(dmd_file))

    if debug : print(dmd_file,os.path.dirname(dmd_file))
    Path(os.path.dirname(dmd_file)).mkdir(parents=True, exist_ok=True)
    with io.open(dmd_file,'w',newline='\n') as f:
        f.write(lines_content)
    
    return dmd_file




def _testings_():

	#/Volumes/SDD2T/PhD/TEC/ionex_igs/2013/igsg2880.13i , From :  /Volumes/SDD2T/PhD/TEC/ionex_igs/2013/zip/igsg2880.13i.Z
	# filename_zip = '/Volumes/SDD2T/PhD/TEC/ionex_igs/2013/zip/igsg2880.13i.Z'
	# filename = '/Volumes/SDD2T/PhD/TEC/ionex_igs/2013/igsg2880.13i'
	# subprocess.call(['7z', 'e', filename_zip,'-o'+os.path.dirname(filename)])

	YEARS = [2013,2014,2015,2017,2018,2019]
	DAYS = list(range(1,366))

	ionex_igs = IONEX(save_directory=os.path.join(os.path.abspath('.'),'ionex_igs'),centre='igs')
	ionex_c1p = IONEX(save_directory=os.path.join(os.path.abspath('.'),'ionex_c1p'),centre='c1p')
	# ionex_gps = IONEX(save_directory=os.path.join(os.path.abspath('.'),'ionex'),centre='cod')
	# ionex_igr = IONEX(save_directory=os.path.join(os.path.abspath('.'),'ionex_igr'),centre='igr')


	ionex_igs.download_ionex(YEARS,DAYS,debug=True)
	ionex_c1p.download_ionex(YEARS,DAYS,debug=True)


def _testing_v2_():

	# import os
	# print(__file__)
	# print(os.path.join(os.path.dirname(__file__), '..'))
	# print(os.path.dirname(os.path.realpath(__file__)))
	# print(os.path.abspath(os.path.dirname(__file__)))

	date = datetime.datetime(2025,2,12)

	ionex = IONEXv2(save_directory=os.path.join(os.path.abspath('.'),'fordmduse'),n_prior_days=4)
	r = ionex.download_ionex_by_date_list([date])
	print(r)

	# ionex.download_ionex(date)
	# ionex.download_c1p(date)

	# print(ionex._get_prioritized_list_of_products(date))


	# ionex.predict_dmd_map(date)


if __name__ == '__main__':



	_testing_v2_()
	# _testings_()

	# quit()

	# # from utilities.IONEX import IONEX,IONEX_15MIN
	# YEAR = 2017
	# DAYS = list(range(1,366))
	# # ionex_gps = IONEX(save_directory=os.path.join(os.path.abspath('.'),'ionex'),centre='cod')

	# # ionex_gps.download_ionex(YEAR,DAYS)

	# ionex_igs15 = IONEX_CDF(save_directory=os.path.join(os.path.abspath('.'),'igs_15min'))

	# # igs15 = ionex_igs15.get_numpy_tecmaps([2013,2014])

	# day = date_to_year_day_number(2013,12,31)+date_to_year_day_number(2014,6,10)
	# time = time_to_index_day_number(11,00,15)
	# print(day,time)
	# # print(date_to_year_day_number(2013,12,31)+date_to_year_day_number(2014,6,10))
	# # print(time_to_index_day_number(16,00,15)-time_to_index_day_number(11,00,15))
	# igs15 = ionex_igs15.get_numpy_tecmaps([2017])
	# print(igs15.shape)


	# fig,axs = plt.subplots(4,5,figsize=(8,8))
	# plt.subplots_adjust(bottom=12)
	
	# for r,raxs in enumerate(axs):
	# 	for c,ax in enumerate(raxs):
	# 		# ax.imshow(np.eye(256))
	# 		# print(index_day_number_to_time(time,15))
	# 		h,m = index_day_number_to_time(time,15)
	# 		ax.set_title("{}:{}".format(format(h, '02d'),format(m, '02d')))
	# 		im = ax.imshow(igs15[day,time])
	# 		divider = make_axes_locatable(ax)
	# 		cax = divider.append_axes("right", size="5%", pad=0.05)
	# 		plt.colorbar(im, cax=cax)
	# 		time+=1
			
	# ax1.imshow(igs15[day,time-1])
	# ax2.imshow(igs15[day,time])
	# ax3.imshow(igs15[day,time+1])
	# ax1.imshow(np.eye(256))
	# plt.show()