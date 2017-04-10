#! /usr/bin/python

import pvlib
import pandas as pd
import datetime
import numpy as np
import zipfile
import re
import os

import matplotlib.pyplot as plt

import seaborn as sns
sns.set_color_codes()

def _read_cache_or_not(cache_name, parse_function, purge_cache):
    data = None
    cache_name = os.path.join('__pycache__', cache_name)
    os.makedirs(os.path.dirname(cache_name), exist_ok = True)
    if not purge_cache:
      try:
        data = pd.read_pickle(cache_name)
      except:
        # cache is missing or bad; ignore it.
        pass
    if data is None:
        data = parse_function()
        data.to_pickle(cache_name)
    return data


def read_cweeds_metadata(purge_cache = False):
    """
    Return the metadata about the stations.
    Index: name
    Columns:
    - name (pretty, for printing)
    - territory (in ALLCAPS, gives the name of the .zip file)
    - directoryname (CamelCaps_1953-2005)
    - ID (which gives the name of the .WY2 file, also used for the cache)
    - latitude (+ means north -- always positive for CWEEDS)
    - longitude (+ means east -- always negative for CWEEDS)
    - time zone as UTC offset
    We try to use the cache unless purge_cache is set.
    """
    return _read_cache_or_not('cweeds-cache.bin', _read_cweeds_metadata, purge_cache)

def _read_cweeds_metadata():
    data = {}
    # CWEEDS was written on windows in Canada, so we probably want CP-1252, but iso-8859-1 is good enough.
    with open('../data/CWEEDS documentation_Release9.txt', encoding='iso-8859-1') as f:
        for line in f:
            if re.match(r'STATION\s*WBAN\s*RAD.CSN\s*WX.CSN\s*LAT\s*LONG\s*MLONG\s*SUN\s*RAD\s*FY\s*LY', line): break
        for line in f:
            # drop newline and EOL whitespace
            line = line.strip()
            if len(line) == 0:
                continue
            # ignore notes
            if line.startswith('NOTE:'):
                continue
            # stop when we get to the appendix
            if line.startswith('APPENDIX C'):
                break
            # keep track of new territories
            if len(line) > 0 and len(line) < 25:
                territory = line
            else:
                # new station!
                uglyname = line[:24].strip()
                prettyname = uglyname.title()
                camelname = re.sub('\s*', '', prettyname)
                # clean up the pretty name:
                prettyname = re.sub(' A$', '', prettyname)
                prettyname = re.sub("Int'L(\.?)", 'Airport', prettyname)
                wban = line[24:29].strip()
                latitude = float(line[46:51])
                longitude = -float(line[52:58]) # longitude is written + meaning West rather than East
                mlong = float(line[59:65]) # median longitude of the time zone
                timezone = -int(mlong) / 15
                firstyear = int(line[74:76]) + 1900
                lastyear = int(line[77:79]) + 1900
                if lastyear < firstyear: lastyear += 100
                data[camelname] = { 'name': prettyname,
                        'territory' : territory,
                        'wban' : wban,
                        'latitude' : latitude,
                        'longitude' : longitude,
                        'timezone' : timezone,
                        'firstyear' : firstyear,
                        'lastyear' : lastyear,
                        'numyears' : lastyear - firstyear,
                }
    data = pd.DataFrame(data).transpose()
    return data

def read_cweeds_data(station, purge_cache = False):
    """
    Look up the weather data for a given weather station.

    Station name is case-insensitive and can be partial (as long as it's unique).

    We calculate everything that doesn't depend on the module & inverter.

    Returns a dataframe with indices the times (hourly data),
    columns for weather, albedo, irradiance (ghi/dni/dhi),
    solar position, etc; as well as the lat/long of the station.

    We cache the data if possible.
    If 'purge_cache' is set, we ignore any existing cache and clobber it.
    """
    metadata = read_cweeds_metadata(purge_cache)
    hits = metadata[metadata.index.to_series().str.contains(station)]
    if len(hits) == 0:
        raise KeyError("Station not found: {}".format(station))
    besthit = hits[hits['numyears'] == hits['numyears'].max()].iloc[0]
    return _read_cache_or_not('cweeds-{wban}.bin'.format(**besthit), lambda : _read_cweeds_data(besthit), purge_cache)

def _read_cweeds_data(metadata):
    """
    Read the CWEEDS .WY2 text file. This is rather slow.
    """
    # Parse the weather data to a frame of series.
    # Unfortunately, seems pd can't handle appending, so we build lists.
    times = []
    ghi = []
    dni = []
    dhi = []
    dni_extra = []
    wind_speed = []
    temp_air = []
    pressure = []
    albedo = []

    # we use these a lot, save some lookups
    albedo_soil = pvlib.irradiance.SURFACE_ALBEDOS['soil']
    albedo_snow = pvlib.irradiance.SURFACE_ALBEDOS['snow']

    zipname = '../data/{territory}.zip'.format(**metadata)
    # the station name we use here is the ugly name, not the pretty name in metadata['name']
    # most stations have the territory name but some don't.
    wy2name_short = '{{}}_{firstyear}-{lastyear}/{wban}.WY2'.format(**metadata).format(metadata.name)
    wy2name = '{}/{}'.format(metadata['territory'], wy2name_short)

    latitude = metadata['latitude']
    longitude = metadata['longitude']
    timezone = datetime.timezone(datetime.timedelta(hours=metadata['timezone']))

    with zipfile.ZipFile(zipname) as zipf:
      def openwy2():
        try:
          return zipf.open(wy2name)
        except KeyError:
          return zipf.open(wy2name_short)
      with openwy2() as f:
        for line in f:
            # yyyymmddhh but hh is 01-24; shift to 00-23
            times.append(datetime.datetime(int(line[6:10]), int(line[10:12]),
                int(line[12:14]), int(line[14:16]) - 1, tzinfo=timezone))

            # values in kJ/m^2 for the entire hour; later we divide by 3.6 to get W/m^2
            dni_extra.append(int(line[16:20])) # extraterrestrial irradiance (sun at ToA)
            ghi.append(int(line[20:24])) # global horizontal irradiance
            dni.append(int(line[26:30])) # direct normal irradiance
            dhi.append(int(line[32:36])) # diffuse horizontal irradiance (ghi - dni)

            # pressure in 10 Pa ; divide by 100 to get kPa
            pressure.append(int(line[85:90]))
            # value in 0.1 C ; divide by 10 to get C
            temp_air.append(int(line[91:95]))
            # value in 0.1 m/s ; divide by 10 to get m/s.
            wind_speed.append(int(line[105:109]))

            # 0 => no snow; 1 => snow; 9 => missing
            str_snow = chr(line[116])
            if str_snow == '0':
                albedo.append(albedo_soil)
            elif str_snow == '1':
                albedo.append(albedo_snow)
            else:
                # Missing. Shitty guess: assume it's snowy if temp < -3 (bad guess!)
                # we probably should guess based on a model that includes precip data and
                # recent temps, which we have access to
                if temp_air[-1] < -3:
                    albedo.append(albedo_snow)
                else:
                    albedo.append(albedo_soil)

    # Pack the data now, before using it below. Also convert to the units we
    # expect (W/m^2 rather than J/(m^2 h), m/s rather than dm/s, etc)
    # And convert the times to np.datetime64 so pandas can run faster.
    times = np.asarray(times, dtype=np.datetime64)
    ghi = np.asarray(ghi, dtype=np.float32) * (1 / 3.6)
    dni = np.asarray(dni, dtype=np.float32) * (1 / 3.6)
    dhi = np.asarray(dhi, dtype=np.float32) * (1 / 3.6)
    dni_extra = np.asarray(dni_extra, dtype=np.float32) * (1 / 3.6)
    wind_speed = np.asarray(wind_speed, dtype=np.float32) * 0.1
    temp_air = np.asarray(temp_air, dtype=np.float32) * 0.1
    pressure = np.asarray(pressure, dtype=np.float32) * 0.01
    albedo = np.asarray(albedo, dtype=np.float32)

    # We don't get zenith/azimuth from the data. Calculate it.
    solpos = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    solar_zenith = np.asarray(solpos['apparent_zenith'], dtype=np.float32)
    solar_azimuth = np.asarray(solpos['azimuth'], dtype=np.float32)

    # Get the air mass (?)
    airmass = pvlib.atmosphere.relativeairmass(solar_zenith)
    am_abs = pvlib.atmosphere.absoluteairmass(airmass, pressure)
    am_abs = np.asarray(am_abs, dtype=np.float32)

    return pd.DataFrame({
        'ghi' : ghi,
        'dni' : dni,
        'dhi' : dhi,
        'dni_extra': dni_extra,
        'wind_speed': wind_speed,
        'temp_air' : temp_air,
        'pressure' : pressure,
        'albedo' : albedo,
        'solar_zenith' : solar_zenith,
        'solar_azimuth' : solar_azimuth,
        'absolute_airmass': am_abs
    }, index = times)

def get_watts_out(data, module, inverter, surface_tilt, surface_azimuth = 180):
    # Get the irradiance on the panel.
    irradiance = pvlib.irradiance.total_irrad(
                    surface_tilt, surface_azimuth,
                    data['solar_zenith'], data['solar_azimuth'],
                    data['dni'], data['ghi'], data['dhi'],
                    dni_extra = data['dni_extra'],
                    albedo = data['albedo'],
                    model='haydavies')
    irradiance.fillna(0, inplace=True)
    #print ("Got the irradiance: ", irradiance)

    # Model the PV panel temperature.
    panel_temp = pvlib.pvsystem.sapm_celltemp(irradiance['poa_global'],
            data['wind_speed'], data['temp_air'])
    #print ("Got the panel temps: ", panel_temp)

    # Get the effective irradiance, which differs from irradiance... somehow.
    aoi = pvlib.irradiance.aoi(surface_tilt, surface_azimuth,
                    data['solar_zenith'], data['solar_azimuth'])
    effective_irradiance = pvlib.pvsystem.sapm_effective_irradiance(
                    irradiance['poa_direct'], irradiance['poa_diffuse'],
                    data['absolute_airmass'], aoi, module)
    #print ("Got the effective irradiance: ", effective_irradiance)

    # Finally, we can get the DC out from the panel, and the AC out from the inverter.
    # Units for AC is watts; DC has several outputs, we use voltage and watts.
    dc = pvlib.pvsystem.sapm(effective_irradiance, panel_temp['temp_cell'], module)
    ac = pvlib.pvsystem.snlinverter(dc['v_mp'], dc['p_mp'], inverter)
    return ac

def plot(series, filename,
        title = None,
        xlabel = None,
        ylabel = None,
        mainlegend = None,
        extralegend = None,
        xtics_count = None,
        yrange = (None, None),
        extraseries = None):
    ax = series.plot(legend = mainlegend, grid=True)
    if extraseries is not None:
        extraseries.plot(grid=False, legend=None, color='green')

    plt.title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)

    if yrange[0] is not None:
        ax.set_ylim(ymin = yrange[0])

    if yrange[1] is not None:
        ax.set_ylim(ymax = yrange[1])

    if xtics_count is not None:
        start, stop = ax.get_xlim()
        ax.set_xticks(np.arange(start, stop, (stop - start) / xtics_count))

    plt.savefig(filename + '.pdf')
    plt.gcf().clear()

def plot_watts_out(series, inverter, filename, title,
        hours_per_item = 1, extraseries = None, xlabel = None, ylabel = None,
        ymax = None):
    maxgeneration = hours_per_item * len(series) * inverter.Paco
    generation = series.sum()
    capacity_factor = generation / maxgeneration * 100.0

    title += ': {:.2f} kWh ({}% capacity)'.format(int(generation) / 1000.0, int(capacity_factor))

    plot(series, filename,
        title = title,
        xlabel = xlabel, ylabel = ylabel,
#        mainlegend = mainlegend,
#        extralegend = extralegend,
#        xtics_count = xtics_count,
        yrange = (0, ymax),
        extraseries = extraseries)

if __name__ == '__main__':
    # Select the PV module and the inverter.
    sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')
    sapm_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')
    module = sandia_modules['Canadian_Solar_CS5P_220M___2009_']
    inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208_208V__CEC_2014_']

    # Select the location. Iqaluit A.
    data = read_cweeds_data('Iqaluit')
    #print ("Got the data: ", data)

    # Select the inclination of the panel. Normally ~ the latitude, and south (180).
    # Latitude means max power at noon on equinox.
    surface_tilt = 60
    surface_azimuth = 180

    ac = get_watts_out(data, module, inverter, surface_tilt, surface_azimuth)

    # Plotting:
    # - group by year
    #      print the daily totals (see variation by time of year)
    #      - group by month
    #           print the daily totals (see variation by day)
    #           print total of each hour (see variation by time of day)
    # print the years (see variation by year)


    # Group by year
    years = ac.groupby(pd.TimeGrouper('A'))
    for year, yeardata in years:
        print ("Year {} group : {}".format(year, yeardata))
        numhours = len(yeardata)
        daily_in_year = yeardata.resample('D').sum()
        average_day_per_month = daily_in_year.resample('M').mean().tshift(-15, 'D')
        print ("Year {} month averages : {}".format(year, average_day_per_month))

        plot_watts_out(daily_in_year, inverter, numhours, "year-{:02d}".format(year.year),
            "Year {:02d}".format(year.year), extraseries = average_day_per_month)

        months = yeardata.groupby(pd.TimeGrouper('M'))
        for month, monthdata in months:
            print ("Month {}".format(month))
            # print daily data
            numhours = len(monthdata)
            monthname = '{:04d}-{:02d}'.format(month.year, month.month)
            plot_watts_out(monthdata.resample('D').sum(), inverter, numhours, "month-{}".format(monthname),
                "Month {}".format(monthname))
            # print hourly data averaged by the day of the month
            plot_watts_out(monthdata.groupby(monthdata.index.hour).mean(), inverter, 24, "average-day-{}".format(monthname),
                "Average daily {}".format(monthname))
