import json
from backtesting import Strategy, Backtest
from backtesting.test import GOOG
from backtesting.lib import resample_apply
import talib
import pandas as pd
import tqdm
import os
# from Scanner import SmaCross


def calculate_pivots(high, low, close):
    central_pivot = (high + low + close) / 3
    bottom_pivot = (high + low) / 2
    top_pivot = 2 * central_pivot - bottom_pivot
    return (top_pivot, central_pivot, bottom_pivot)


# pivots = None


def CPR(high, low, close, column):
    # global pivots
    # if pivots == None:
    if not os.path.exists(f'{stockName}_pivot.csv'):
        pivots = pd.DataFrame(columns=['bottom', 'central', 'top'])
        pivots.loc[0] = [pd.NA, pd.NA, pd.NA]
        for index in tqdm.trange((len(high)-1)):
            # high, low, close = ohlc['high'], ohlc['low'], ohlc['close']
            central_pivot = (high[index] + low[index] + close[index]) / 3
            bottom_pivot = (high[index] + low[index]) / 2
            top_pivot = 2 * central_pivot - bottom_pivot
            calculate_pivots = sorted([central_pivot, bottom_pivot, top_pivot])
            pivots.loc[index+1] = calculate_pivots
        pivots.to_csv(f'{stockName}_pivot.csv', sep=',')
    else:
        pivots = pd.read_csv(f'{stockName}_pivot.csv')
    return pivots[column]


class CPRPivot(Strategy):
    def init(self):
        close = self.data.Close
        self.ema63_daily = self.I(talib.EMA, close, 63)
        self.daily_data = resample_apply(
            '1D', lambda x: x, self.data.df, plot=False)
        self.pivots_top_daily = self.I(
            CPR, self.daily_data[1], self.daily_data[2], self.daily_data[3], 'top', scatter=True)
        self.pivots_central_daily = self.I(
            CPR, self.daily_data[1], self.daily_data[2], self.daily_data[3], 'central', plot=False)
        self.pivots_bottom_daily = self.I(
            CPR, self.daily_data[1], self.daily_data[2], self.daily_data[3], 'bottom', plot=False)
        print("Completed Initialization")
        self.daily_trigger = False
        # self.ema63 = self.I(talib.EMA, close, 63)
        # self.pivots = self.I(CPR, self.data)
        # self.data_5min = self.data

    def next(self):
        index = -1
        previousDayDataIndex = -75
        pivot = (self.pivots_central_daily[index],
                 self.pivots_top_daily[index], self.pivots_bottom_daily[index])

        if (len(self.pivots_bottom_daily) < 151):
            # Skip testing 1st day as we don't have previous day pivot
            return

        current_ema = self.ema63_daily[index]

        if (self.pivots_central_daily[-1] != self.pivots_central_daily[-2]):
            previousDayPivot = (self.pivots_central_daily[previousDayDataIndex],
                                self.pivots_top_daily[previousDayDataIndex], self.pivots_bottom_daily[previousDayDataIndex])
            isAscending = pivot[2] > previousDayPivot[1]
            isNarrowCPR = (pivot[0] - pivot[2]) < pivot[0] * (0.006)
            emaAbovePivot = current_ema > pivot[1]
            if isAscending and isNarrowCPR and emaAbovePivot:
                self.daily_trigger = True
            else:
                self.daily_trigger = False

        # isPreviousCPRNarrow = (
        #     previousDayPivot[0] - previousDayPivot[2]) < previousDayPivot[0] * 0.003
        current_candle_close = self.data.Close[-1]
        time = self.data.index[-1].to_pydatetime().time()
        # print(pivot, previousDayPivot, sep=":::")
        # if self.data.index[-1].to_pydatetime().date().month == 8 and self.data.index[-1].to_pydatetime().date().day == 1 and self.data.index[-1].to_pydatetime().date().year == 2022:
        #     breakpoint()

        # Do not take trades after 12
        if self.position.size == 0 and time.hour >= 12:
            return

        # Day indicators
        if self.daily_trigger:
            if current_candle_close > current_ema:
                if self.position.size == 0 and self.position.pl == 0:
                    self.buy(
                        limit=self.data.High[-1], sl=current_ema, tp=self.data.High[-1] * 1.01)
                    print("Bought")
        if current_candle_close < pivot[2] and self.data.Close[-2] < pivot[2] and self.position.is_long:
            self.position.close()
            print("Sold as stop loss hit")
        if time.hour == 15 and time.minute == 10:
            if self.position.size != 0:
                self.position.close()
                print("Sold as time up")


stockName = "Dixon"
with open(f'{stockName}Data.json', 'r') as file:
    data = file.read()
data = json.loads(data)
df = pd.DataFrame(data.get('data'))
df = df.rename(columns={'o': 'Open', 'c': 'Close',
                        'h': 'High', 'l': 'Low', 'v': 'Volume'})
df = df.drop('oi', axis=1)
df = df.drop('t', axis=1)
df['Time'] = pd.to_datetime(df['Time'], dayfirst=False)
# df['t'] = pd.to_numeric(pd.to_datetime(df['t']))
df = df.set_index('Time')
bt = Backtest(df, CPRPivot,
              cash=100000)
output = bt.run()
print(output)
bt.plot(resample='15Min')
