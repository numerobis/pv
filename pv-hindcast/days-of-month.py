import calendar
import hindcast
import numpy as np
import os
import pandas as pd
import pvlib
import sys

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('location', help = 'Station name', default = 'Iqaluit')
    parser.add_argument('-t', '--tilt', type=float, help = 'Tilt angle of panels (0 = flat, 90 = vertical)')
    parser.add_argument('-a', '--azimuth', type=float, help='Azimuth angle of panels (180 = South)', default = 180)
    args = parser.parse_args()

    # Select the PV module and the inverter.
    sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')
    sapm_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')
    module = sandia_modules['Canadian_Solar_CS5P_220M___2009_']
    inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208_208V__CEC_2014_']

    # Read the data.
    station = args.location
    os.makedirs(station, exist_ok = True)
    metadata = hindcast.get_cweeds_metadata(station)
    print ("Reading data for {name}, {latitude} x {longitude}\nYears {firstyear}-{lastyear}".format(**metadata))

    data = hindcast.read_cweeds_data(metadata)

    # what tilt angles should we use?
    if args.tilt is None:
        surface_tilt = np.arange(0, 95, 5)
    else:
        surface_tilt = [ args.tilt ]
    azimuth = args.azimuth

    # what order statistic do we care about: mean and x%
    pct = 10

    def get_stats(series):
        return series.agg({
                'mean': np.mean,
                '%': lambda x: np.percentile(x, pct)
        })

    # Simulate the module at each angle of tilt.
    #
    # Gather up the results by tilt, so that we can superimpose them on the
    # same Y range.
    annual_stats_by_tilt = []
    monthly_stats_by_tilt = []
    for tilt in surface_tilt:
        byTilt = hindcast.get_watts_out(data, module, inverter, tilt, azimuth)

        # first plot the average / 10% statistic daily total by day of year
        daily = byTilt.resample('D').apply(np.sum)
        dailies = daily.groupby([daily.index.month, daily.index.day])
        stats = get_stats(dailies)
        # remap the index so we see Dec 5 rather than (12, 5)
        stats.index = stats.index.map(lambda x : '{} {}'.format(calendar.month_abbr[x[0]], x[1]))
        annual_stats_by_tilt.append(stats)

        # group all the march data, etc
        byMonth = byTilt.groupby([byTilt.index.month])
        monthly_stats = {}
        for month, monthdata in byMonth:
            # group all the 11am data in march, etc
            hourly = monthdata.groupby([monthdata.index.hour])

            # aggregate to get the mean and 10% statistic
            stats = get_stats(hourly)
            monthly_stats[month] = stats
        monthly_stats_by_tilt.append(monthly_stats)

    # Find the maximum value for any day in any tilt.
    # The mean is usually bigger than the 10%, but just take the max of the
    # mean and the 10% anyway.
    max_Wh_per_day = max([stats.max().max() for stats in annual_stats_by_tilt])

    # Plot the annual stats, one per tilt level.
    for tilt, stats in zip(surface_tilt, annual_stats_by_tilt):
        hindcast.plot_watts_out(stats['mean'], inverter, '{}/average-year-tilt-{:02.0f}-aziumuth-{:02.0f}'.format(station, tilt, azimuth),
            "Average year with panel at {:2.0f} degrees facing {:2.0f}".format(tilt, azimuth),
            extraseries = stats['%'], hours_per_item = 24,
            xlabel = 'Date', ylabel = 'Wh per day', ymax = max_Wh_per_day)

    # Find the maximum value for any hour in any month and tilt.
    #max_Wh_per_hour = max([stats.max().max()
    #                    for stats in monthly_stats
    #                    for monthly_stats in monthly_stats_by_tilt])
#
#    for tilt, monthly_stats in zip(surface_tilt, monthly_stats_by_tilt):
#        for month, stats in monthly_stats.items():
#            # plot the mean and 10% statistic
#            hindcast.plot_watts_out(stats['mean'], inverter, 'average-day-{:02d}-tilt-{:02d}'.format(month, tilt),
#                "Average day in {} with panel at {} degrees".format(calendar.month_abbr[month], tilt),
#                extraseries = stats['%'], xlabel = 'Time of day', ylabel = 'W output', ymax = max_Wh_per_hour)
