# Imports
from logging import exception
import os
import re
from dotenv import dotenv_values
import traceback
import numpy as np
import pandas as pd
import netCDF4
import sys
import xarray as xr
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from calendar import monthrange
from opendap_download.multi_processing_download import DownloadManager
import time

if len(sys.argv) < 2:
    print('Please provide file name as argument.')
    sys.exit(1)

start = time.time()
# Authentication for MERRA download
config = dotenv_values(".env")
username = config["username"]
password = config["key"]

# databases is a dict with database_id as key and database_names as values
# These IDs and Names of database in which field is stored, can be looked up by ID here: https://gmao.gsfc.nasa.gov/pubs/docs/Bosilovich785.pdf 
field_id = 'T2M' # ID of field in MERRA-2 - find ID here: https://gmao.gsfc.nasa.gov/pubs/docs/Bosilovich785.pdf 
field_name = 'temperature_MERRA' # Name of field to be stored with downloaded data (can use any name you like)
database_name = 'M2I1NXASM' # Name of database in which field is stored, can be looked up by ID here: https://gmao.gsfc.nasa.gov/pubs/docs/Bosilovich785.pdf 
database_id = 'inst1_2d_asm_Nx' # ID of database database in which field is stored, also can be looked up by ID here: https://gmao.gsfc.nasa.gov/pubs/docs/Bosilovich785.pdf 
conversion_factor = lambda x: x - 273.15
aggregator = 'mean'


####### CONSTANTS - DO NOT CHANGE BELOW THIS LINE #######
lat_coords = np.arange(0, 361, dtype=int)
lon_coords = np.arange(0, 576, dtype=int)
database_url = 'https://goldsmr4.gesdisc.eosdis.nasa.gov/opendap/MERRA2/' + database_name + '.5.12.4/'
NUMBER_OF_CONNECTIONS = 5


####### DOWNLOAD DATA #########
# Translate lat/lon into coordinates that MERRA-2 understands
def translate_year_to_file_number(year):
    """
    The file names consist of a number and a meta data string. 
    The number changes over the years. 1980 until 1991 it is 100, 
    1992 until 2000 it is 200, 2001 until 2010 it is  300 
    and from 2011 until now it is 400.
    """
    file_number = ''
    year = int(year)
    if year >= 1980 and year < 1992:
        file_number = '100'
    elif year >= 1992 and year < 2001:
        file_number = '200'
    elif year >= 2001 and year < 2011:
        file_number = '300'
    elif year >= 2011:
        file_number = '400'
    else:
        print(year)
        raise Exception('The specified year is out of range.')
    return file_number


def generate_url_params(parameter, time_para, lat_para, lon_para):
    """Creates a string containing all the parameters in query form"""
    parameter = map(lambda x: x + time_para, parameter)
    parameter = map(lambda x: x + lat_para, parameter)
    parameter = map(lambda x: x + lon_para, parameter)
    return ','.join(parameter)
 

def generate_file_name(loc, year, month, day, dataset_name):
    file_num = translate_year_to_file_number(year)
    return '{loc}_{num}.{name}.{y}{m}{d}.nc4'.format(
                    loc=loc,num=file_num, name=dataset_name, 
                    y=year, m=month, d=day)

def translate_lat_to_geos5_native(latitude):
    """
    The source for this formula is in the MERRA2 
    Variable Details - File specifications for GEOS pdf file.
    The Grid in the documentation has points from 1 to 361 and 1 to 576.
    The MERRA-2 Portal uses 0 to 360 and 0 to 575.
    latitude: float Needs +/- instead of N/S
    """
    return ((latitude + 90) / 0.5)

def translate_lon_to_geos5_native(longitude):
    """See function above"""
    return ((longitude + 180) / 0.625)

def find_closest_coordinate(calc_coord, coord_array):
    """
    Since the resolution of the grid is 0.5 x 0.625, the 'real world'
    coordinates will not be matched 100% correctly. This function matches 
    the coordinates as close as possible. 
    """
    # np.argmin() finds the smallest value in an array and returns its
    # index. np.abs() returns the absolute value of each item of an array.
    # To summarize, the function finds the difference closest to 0 and returns 
    # its index. 
    index = np.abs(coord_array-calc_coord).argmin()
    return coord_array[index]

def generate_download_link(loc, date, base_url, dataset_name, url_params):
    year, month, day = date.split('-')
    file_name = generate_file_name(loc, year, month, day, dataset_name)
    query = '{base}{y}/{m}/{name}.nc4?{params}'.format(
                    base=base_url, y=year, m=month, 
                    name=file_name, params=url_params)
    return query


def generate_url_with_params(loc, lat, lon, date):
    lat_coord = translate_lat_to_geos5_native(lat)
    lon_coord = translate_lon_to_geos5_native(lon)
    # Find the closest coordinate in the grid.
    lat_closest = find_closest_coordinate(lat_coord, lat_coords)
    lon_closest = find_closest_coordinate(lon_coord, lon_coords)
    # Generate URLs for scraping
    requested_lat = '[{lat}:1:{lat}]'.format(lat=lat_closest)
    requested_lon = '[{lon}:1:{lon}]'.format(lon=lon_closest)
    parameter = generate_url_params([field_id], '[0:1:23]', requested_lat, requested_lon)
    generated_URL = generate_download_link(loc, date, database_url, database_id, parameter)
    return generated_URL

# download_manager = DownloadManager()
# download_manager.set_username_and_password(username, password)
# download_manager.download_path = 'downloads' + '/' + loc
# download_manager.download_urls = generated_URL
# download_manager.start_download(NUMBER_OF_CONNECTIONS)

def extract_date(data_set):
    """
    Extracts the date from the filename before merging the datasets. 
    """ 
    if 'HDF5_GLOBAL.Filename' in data_set.attrs:
        f_name = data_set.attrs['HDF5_GLOBAL.Filename']
    elif 'Filename' in data_set.attrs:
        f_name = data_set.attrs['Filename']
    else: 
        raise AttributeError('The attribute name has changed again!')
    # find a match between "." and ".nc4" that does not have "." .
    exp = r'(?<=\.)[^\.]*(?=\.nc4)'
    res = re.search(exp, f_name).group(0)
    # Extract the date. 
    y, m, d = res[0:4], res[4:6], res[6:8]
    date_str = ('%s-%s-%s' % (y, m, d))
    data_set = data_set.assign(date=date_str)
    return data_set


complete_dataset = pd.read_csv(sys.argv[1])

for index, row in complete_dataset.iterrows():
    loc, lat, lon = [row['station_name'], row['latitude'], row['longitude']]
    date = row['collected_at']
    year, month, day = date.split('-')
    if (int(year) < 1980):
        continue
    file_name = generate_file_name('MERRA2', year, month, day, database_id)
    if not os.path.exists(field_name + '/' + loc + '/' + file_name):
        download_manager = DownloadManager()
        download_manager.set_username_and_password(username, password)
        download_manager.download_path = field_name + '/' + loc
        print('Downloading file: ' + field_name + ' of ' + loc + ' @ ' + date)
        download_manager.download_urls = [generate_url_with_params('MERRA2', lat, lon, date)]
        download_manager.start_download(NUMBER_OF_CONNECTIONS)
    else:
        print('File already downloaded: ' + field_name + ' of ' + loc + ' @ ' + date)
    
    try:
        with xr.open_mfdataset(field_name + '/' + loc + '/' + file_name) as data_set:
            dfs = data_set.to_dataframe()
            daily_mean = dfs[field_id].agg(aggregator)
            complete_dataset.loc[index, field_name] = conversion_factor(daily_mean)
             
    except Exception:
        print('Error while reading file: ' + field_name + ' of ' + loc + ' @ ' + date)
complete_dataset.to_csv(sys.argv[1] + '_MERRA2_processed.csv');
end = time.time()
print('Time elapsed: ' + "{:.2f}".format(end - start) + ' seconds')