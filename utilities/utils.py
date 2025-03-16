import os
import glob
import datetime

import pycurl
import certifi
from io import BytesIO
import hatanaka
import numpy as np
import re

from atomicwrites import atomic_write
from functools import partial

import requests
from typing import List

from multiprocessing import Pool, cpu_count

from requests.packages import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_N_PROCESSES = cpu_count() // 2
MAX_CHILEDS = 1

RNX_root = 'RNX'
ION_root = 'ION'
CLK_root = 'CLK'
SP3_root = 'SP3'
OUTPUT_root = 'OUT'
TEMP_root = 'TEMP'

VERIFY_REST_SECURITY = False


def gLab_output_to_numpy(output_file):
    NEU_START,NEU_END = 17,20
    with open(output_file,'r') as f:
        # list(map(float,l.split()[NEU_START:NEU_END]))
        lines = f.readlines()
        neu=np.array([list(map(float,l.split()[NEU_START:NEU_END])) for l in lines if re.match('OUTPUT*', l)])#.reshape(3,-1)
        epochs = np.array([float(l.split()[3]) for l in lines if re.match('OUTPUT*', l)])
        # print(output_lines)

        return neu,epochs

def date_to_glab_output_file(date,station_name,agency_name):
    dt = date - datetime.datetime(year=date.year,month=1,day=1) + datetime.timedelta(days=1)
    year = date.year%100
    res = '{}{}{:03d}0.{:02d}out'.format(station_name,agency_name,dt.days,year)
    return res

def date_to_rinex_name(date,station_name):

    dt = date - datetime.datetime(year=date.year,month=1,day=1) + datetime.timedelta(days=1)

    rinex_year = date.year%100
    rinex_day = date.day
    compressed = '{}{:03d}0.{:02d}d'.format(station_name,dt.days,rinex_year)
    decompressed = '{}{:03d}0.{:02d}o'.format(station_name,dt.days,rinex_year)
    return compressed,decompressed,date.year,dt.days


def datetime_to_gpsweekday(date):
    zero_epoch = datetime.datetime(1980, 1, 6)
    
    week = (date - zero_epoch).days // 7
    day = (date - zero_epoch).days % 7

    return week,day

def date_to_clk(date,agency):
    gps_week,gps_day = datetime_to_gpsweekday(date)
    file_name = '{}{}{}.clk_30s'.format(agency,gps_week,gps_day)
    return file_name

def date_to_sp3(date,agency):
    gps_week,gps_day = datetime_to_gpsweekday(date)
    file_name = '{}{}{}.sp3'.format(agency,gps_week,gps_day)
    return file_name

def date_to_doy(date):
    dt = date - datetime.datetime(year=date.year,month=1,day=1)
    return dt.days+1


def download_and_save_file(url,file_path):
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
    
    # print(file_path,os.path.isfile(file_path),url)
    if os.path.isfile(file_path): return file_path
    data_zipped = download(url)
    if data_zipped is None: 
        return None
    

    ephem_bytes = hatanaka.decompress(data_zipped)
    with atomic_write(file_path, mode='wb', overwrite=True) as f:
        f.write(ephem_bytes)

    return file_path
        
def download_clk(dates_list=[],agencies_list=['igs'],download_folder=CLK_root,log_filename='download_clk.log'):

    base_urls = [
        'https://cddis.nasa.gov/archive/gnss/products'
        # 'https://urs.earthdata.nasa.gov/archive/gnss/products'
    ]

    # download_folder_zip = os.path.join(download_folder,'zip')

    files_to_download_dict = {}

    for agency in agencies_list:

        for date in dates_list:

            gps_week,gps_day = datetime_to_gpsweekday(date)

            Z_file_name = '{}{}{}.clk_30s.Z'.format(agency,gps_week,gps_day)
            file_name = '{}{}{}.clk_30s'.format(agency,gps_week,gps_day)

            extracted_file_path = os.path.join(download_folder,file_name)
            os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

            if os.path.isfile(extracted_file_path):
                continue
            else:
                #TODO download the file
                for base_url in base_urls:
                    url = '{}/{}/{}'.format(base_url,gps_week,Z_file_name)
                    # print(url)
                    files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
                
    urls_to_download = [value['url'] for value in files_to_download_dict.values()]

    # print("There are {} CPUs on this machine ".format(cpu_count()))
    pool = Pool(MAX_N_PROCESSES)
    results = pool.starmap(download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
    pool.close()
    pool.join()

    # for url,file_path in zip(urls_to_download,list(files_to_download_dict.keys())):
    #     download_and_save_file(url,file_path)

    os.makedirs(TEMP_root,exist_ok=True)
    log_filename = os.path.join(TEMP_root,log_filename)

    for file_path,data_dict in files_to_download_dict.items():
        if not os.path.isfile(file_path):
            with open(log_filename,'a') as logfile:    
                logfile.writelines("missing : {} {}\n".format(data_dict['date'],data_dict['url']))
            


             
def download_rinex(station_name,dates_list=[],download_folder=RNX_root,log_filename='download_rinex.log'):

    base_urls = [
        'https://garner.ucsd.edu/archive/garner/rinex'
    ]

    # download_folder_zip = os.path.join(download_folder,'zip')

    files_to_download_dict = {}

    for date in dates_list:

        rinex_compressed_name,rinex_decopressed_name,year,day = date_to_rinex_name(date,station_name)

        Z_file_name = '{}.Z'.format(rinex_compressed_name)
        file_name = rinex_decopressed_name

        # print(Z_file_name,file_name)

        extracted_file_path = os.path.join(download_folder,file_name)
        os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

        # if os.path.isfile(extracted_file_path):
            # continue
        # else:
        #TODO download the file
        for base_url in base_urls:
            url = '{}/{}/{:03d}/{}'.format(base_url,year,day,Z_file_name)
            print(url)
            files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
                
    urls_to_download = [value['url'] for value in files_to_download_dict.values()]

    # print(urls_to_download)

    # print("There are {} CPUs on this machine ".format(cpu_count()))
    pool = Pool(MAX_N_PROCESSES)
    results = pool.starmap(download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
    # print(results)
    pool.close()
    pool.join()

    # for url,file_path in zip(urls_to_download,list(files_to_download_dict.keys())):
    #     download_and_save_file(url,file_path)

    os.makedirs(TEMP_root,exist_ok=True)
    log_filename = os.path.join(TEMP_root,log_filename)

    for file_path,data_dict in files_to_download_dict.items():
        if not os.path.isfile(file_path):
            with open(log_filename,'a') as logfile:
                # log_lines = logfile.readlines()
                line = "missing : {} {}\n".format(data_dict['date'],data_dict['url'])
                # if not line in log_lines : 
                logfile.writelines(line)

def generate_dates(year,n_contious_dates,n_generations=1,up_to : datetime.datetime = None):

    end_day = datetime.datetime(year,12,31) - datetime.timedelta(days=n_contious_dates-1)
    if up_to:
        end_day = up_to - datetime.timedelta(days=n_contious_dates-1)
    start_day = datetime.datetime(year,1,1)

    day_range = end_day - start_day

    year_days = np.array([start_day + datetime.timedelta(days=i) for i in range(day_range.days+1)])

    generations = []

    for g in range(n_generations):
        idx = np.random.choice(list(range(year_days.shape[0])),1)[0]
        random_date = year_days[idx]#np.random.choice(year_days,1)[0]
        random_sequence = [random_date+datetime.timedelta(days=i) for i in range(n_contious_dates)]
        generations.append(random_sequence)

        seq_to_remove = random_sequence + [random_date-datetime.timedelta(days=i) for i in range(1,n_contious_dates)]

        year_days = np.array(list(set(year_days)-set(seq_to_remove)))


        # print(random_date)
        # print(random_sequence)
        # print(seq_to_remove)
    # print([])
    
    return generations


##################################
#            IONEX                     
##################################

def rename_ionex_to_old_format(files_path: List[str]):

    REG_EXPRESSION = '\D{3}\W(\D{3})0OPS(\D{3})_\d{2}(\d{2})(\d{4})'
    reg = re.compile(REG_EXPRESSION)
    for path_str in files_path:
        try:
            agency,prod,year,day = reg.search(path_str).groups()
            old_file_name = '{}g{}.{}i'.format(agency.lower(),day, year)

            dir = os.path.dirname(path_str)
            new_file = os.path.join(dir,old_file_name)
            os.rename(path_str,new_file)
        except:pass

def date_to_ionex_name_v2(date,agency):

    AGENCIES : List[str] = ['IGS','JPL','ESA','COD']
    OLD_AGENCIES_PRIORITY : List[str] = ['igs','jpl','upc','igr','jpr','upr','ckm']
    # RESOLUTION : List[str]  = ['02H']
    # SOLUTION_TYPES : List[str]  = ['FIN']
    # CAMPAINGE : List[str]  = 'OPS'

    names = []
    zip_names = []

    doy = '{:03d}'.format(date_to_doy(date))
    '''Priority #3-6'''
    if agency.upper() in AGENCIES:
        file_name = f'{agency.upper()}0OPSFIN_{date.year}{doy}0000_01D_02H_GIM.INX'
        names.append(file_name)
        zip_names.append(f'{file_name}.gz')
        old_file_name = '{}g{:03d}0.{:02d}i'.format(agency, date_to_doy(date), date.year % 100)
        # names.append(old_file_name)

    if agency in OLD_AGENCIES_PRIORITY:
        file_name = '{}g{:03d}0.{:02d}i'.format(agency, date_to_doy(date), date.year % 100)
        names.append(file_name)
        zip_names.append(f'{file_name}.Z')	

    dt = date - datetime.datetime(year=date.year,month=1,day=1) + datetime.timedelta(days=1)

    return zip_names,names,date.year,dt.days

def download_ionex_v2(dates_list=[],agencies_list=['igs','ckm'],download_folder=ION_root,log_filename='download_ionex.log'):
    base_urls = [
        'https://cddis.nasa.gov/archive/gnss/products/ionex'
    ]

    # download_folder_zip = os.path.join(download_folder,'zip')

    files_to_download_dict = {}
    for agency in agencies_list:
        for date in dates_list:

            # _name,year,day = date_to_ionex_name(date,agency)
            # print(date,agency)
            zip_names,file_names,year,day = date_to_ionex_name_v2(date,agency)

            # print(zip_names,file_names)

            for zip_name,file_name in zip(zip_names,file_names):

                if agency == 'ckm':
                    zip_name = 'topex/{}'.format(zip_name)

                # print(zip_name,file_name)

                extracted_file_path = os.path.join(download_folder,file_name)
                os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

                # if os.path.isfile(extracted_file_path):
                    # continue
                # else:
                #TODO download the file
                for base_url in base_urls:
                    url = '{}/{}/{:03d}/{}'.format(base_url,year,day,zip_name)

                    # print(extracted_file_path,url)
                    files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
                
    urls_to_download = [value['url'] for value in files_to_download_dict.values()]

    # print(files_to_download_dict)
    # print("There are {} CPUs on this machine ".format(cpu_count()))
    pool = Pool(MAX_N_PROCESSES)
    # pool = Pool(1)
    results = pool.starmap(download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
    # print(results)
    # rename_ionex_to_old_format(results)
    pool.close()
    pool.join()

    # for url,file_path in zip(urls_to_download,list(files_to_download_dict.keys())):
    #     download_and_save_file(url,file_path)

    os.makedirs(TEMP_root,exist_ok=True)
    log_filename = os.path.join(TEMP_root,log_filename)

    for file_path,data_dict in files_to_download_dict.items():
        if not os.path.isfile(file_path):
            with open(log_filename,'a') as logfile:
                # log_lines = logfile.readlines()
                line = "missing : {} {}\n".format(data_dict['date'],data_dict['url'])
                # if not line in log_lines : 
                logfile.writelines(line)

def date_to_ionex_name(date,agency):
    '''
    Deprecated
    '''
    dt = date - datetime.datetime(year=date.year,month=1,day=1) + datetime.timedelta(days=1)
    _year = date.year%100
    day = date.day
    name = '{}g{:03d}0.{:02d}i'.format(agency,dt.days,_year)
    # decompressed = '{}g{:03d}0.{:02d}o'.format(agency,dt.days,_year)
    return name,date.year,dt.days

def download_ionex(dates_list=[],agencies_list=['igs','ckm'],download_folder=ION_root,log_filename='download_ionex.log'):
    '''
    Deprecated
    '''
    base_urls = [
        'https://cddis.nasa.gov/archive/gnss/products/ionex'
    ]

    # download_folder_zip = os.path.join(download_folder,'zip')

    files_to_download_dict = {}
    for agency in agencies_list:

        for date in dates_list:

            _name,year,day = date_to_ionex_name(date,agency)

            Z_file_name = '{}.Z'.format(_name)
            file_name = _name

            if agency == 'ckm':
                _name,year,day = date_to_ionex_name(date,agency)
                Z_file_name = 'topex/{}.Z'.format(_name)

            # print(Z_file_name,file_name)

            extracted_file_path = os.path.join(download_folder,file_name)
            os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

            # if os.path.isfile(extracted_file_path):
                # continue
            # else:
            #TODO download the file
            for base_url in base_urls:
                url = '{}/{}/{:03d}/{}'.format(base_url,year,day,Z_file_name)

                
                files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
                
    urls_to_download = [value['url'] for value in files_to_download_dict.values()]

    # print(urls_to_download)

    # print("There are {} CPUs on this machine ".format(cpu_count()))
    pool = Pool(MAX_N_PROCESSES)
    # pool = Pool(1)
    results = pool.starmap(download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
    # print(results)
    pool.close()
    pool.join()

    # for url,file_path in zip(urls_to_download,list(files_to_download_dict.keys())):
    #     download_and_save_file(url,file_path)

    os.makedirs(TEMP_root,exist_ok=True)
    log_filename = os.path.join(TEMP_root,log_filename)

    for file_path,data_dict in files_to_download_dict.items():
        if not os.path.isfile(file_path):
            with open(log_filename,'a') as logfile:
                # log_lines = logfile.readlines()
                line = "missing : {} {}\n".format(data_dict['date'],data_dict['url'])
                # if not line in log_lines : 
                logfile.writelines(line)

##################################
#             SP3                    
##################################

def rename_sp3_to_old_format(files_path: List[str]):

    REG_EXPRESSION = '\D{2}\d{1}\W(\D{3})0OPS(\D{3})_(\d{4})(\d{3})'
    reg = re.compile(REG_EXPRESSION)
    for path_str in files_path:
        try:
            agency,prod,year,doy = reg.search(path_str).groups()
            date = datetime.datetime(int(year),1,1) + datetime.timedelta(days=int(doy)-1)
            old_file_name = date_to_sp3(date,agency.lower())

            dir = os.path.dirname(path_str)
            new_file = os.path.join(dir,old_file_name)
            os.rename(path_str,new_file)
        except:pass

def prioritized_sp3_filenames(date):
    names = []
    zip_names = []
    AGENCIES = ['igs','jpl']

    RESOLUTION = ['15M','05M']
    SOLUTION_TYPES = ['FIN','RAP','ULT']

    CAMPAINGE = 'OPS'

    gps_week,gps_day = datetime_to_gpsweekday(date)
    '''Priority #1,#2'''
    for agency in AGENCIES:
        file_name = '{}{}{}.sp3'.format(agency,gps_week,gps_day)
        names.append(file_name)
        zip_names.append(f'{file_name}.Z')

    doy = '{:03d}'.format(date_to_doy(date))
    '''Priority #3-6'''
    for solution in SOLUTION_TYPES:
        for agency,temporal_resolution in zip(AGENCIES,RESOLUTION):
            file_name = f'{agency.upper()}0{CAMPAINGE}{solution}_{date.year}{doy}0000_01D_{temporal_resolution}_ORB.SP3'
            # print(agency.upper(),temporal_resolution)
            names.append(file_name)
            zip_names.append(f'{file_name}.gz')

    return zip_names,names

def download_sp3_v2(dates_list=[],download_folder=SP3_root,log_filename='download_sp3.log'):

    base_urls = [
        'https://cddis.nasa.gov/archive/gnss/products'
        # 'https://urs.earthdata.nasa.gov/archive/gnss/products'
    ]

    # download_folder_zip = os.path.join(download_folder,'zip')

    files_to_download_dict = {}

    for date in dates_list:

        zip_names,names = prioritized_sp3_filenames(date)
        for Z_file_name,file_name in zip(zip_names,names):

            extracted_file_path = os.path.join(download_folder,file_name)
            os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

            if os.path.isfile(extracted_file_path):
                break
                continue
            else:
                #TODO download the file
                file_url_exist = False
                gps_week,gps_day = datetime_to_gpsweekday(date)
                for base_url in base_urls:
                    url = '{}/{}/{}'.format(base_url,gps_week,Z_file_name)
                    
                    response = requests.head(url,verify=VERIFY_REST_SECURITY)
                    if response.status_code == 200:
                        files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
                        file_url_exist = True
                        break
                if file_url_exist: break

    
                
    urls_to_download = [value['url'] for value in files_to_download_dict.values()]

    # return urls_to_download

    # print("There are {} CPUs on this machine ".format(cpu_count()))
    pool = Pool(MAX_N_PROCESSES)
    results = pool.starmap(download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
    # rename_sp3_to_old_format(results)
    pool.close()
    pool.join()

    # for url,file_path in zip(urls_to_download,list(files_to_download_dict.keys())):
    #     download_and_save_file(url,file_path)

    os.makedirs(TEMP_root,exist_ok=True)
    log_filename = os.path.join(TEMP_root,log_filename)

    for file_path,data_dict in files_to_download_dict.items():
        if not os.path.isfile(file_path):
            with open(log_filename,'a') as logfile:    
                logfile.writelines("missing : {} {}\n".format(data_dict['date'],data_dict['url']))

def download_sp3(dates_list=[],agencies_list=['igs'],download_folder=SP3_root,log_filename='download_sp3.log'):



    base_urls = [
        'https://cddis.nasa.gov/archive/gnss/products'
        # 'https://urs.earthdata.nasa.gov/archive/gnss/products'
    ]

    # download_folder_zip = os.path.join(download_folder,'zip')

    files_to_download_dict = {}

    for agency in agencies_list:

        for date in dates_list:

            gps_week,gps_day = datetime_to_gpsweekday(date)

            Z_file_name = '{}{}{}.sp3.Z'.format(agency,gps_week,gps_day)
            file_name = '{}{}{}.sp3'.format(agency,gps_week,gps_day)

            extracted_file_path = os.path.join(download_folder,file_name)
            os.makedirs(os.path.dirname(extracted_file_path), exist_ok=True)

            if os.path.isfile(extracted_file_path):
                continue
            else:
                #TODO download the file
                for base_url in base_urls:
                    url = '{}/{}/{}'.format(base_url,gps_week,Z_file_name)
                    
                    files_to_download_dict[extracted_file_path] = {'url':url,'date':date}
                
    urls_to_download = [value['url'] for value in files_to_download_dict.values()]

    # print("There are {} CPUs on this machine ".format(cpu_count()))
    pool = Pool(MAX_N_PROCESSES)
    results = pool.starmap(download_and_save_file,zip(urls_to_download,list(files_to_download_dict.keys())))
    pool.close()
    pool.join()

    # for url,file_path in zip(urls_to_download,list(files_to_download_dict.keys())):
    #     download_and_save_file(url,file_path)

    os.makedirs(TEMP_root,exist_ok=True)
    log_filename = os.path.join(TEMP_root,log_filename)

    for file_path,data_dict in files_to_download_dict.items():
        if not os.path.isfile(file_path):
            with open(log_filename,'a') as logfile:    
                logfile.writelines("missing : {} {}\n".format(data_dict['date'],data_dict['url']))


##################################
#                                 
##################################

##################################
#                                 
##################################
##################################
#                                 
##################################
