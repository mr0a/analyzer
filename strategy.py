import json
from backtesting import Strategy, Backtest
from backtesting.test import GOOG
from backtesting.lib import resample_apply
import talib
import pandas as pd
import tqdm
import os
# from Scanner import SmaCross

CPR_BOTTOM = 0
CPR_CENTRAL = 1
CPR_TOP = 2

NARROW_THRESHOLD = 2.6
WIDE_CPR_THRESHOLD = 10

GAP_UP_THRESHOLD = 1
GAP_DOWN_THRESHOLD = 1

CPR_GAP_UP_THRESHOLD = 1
CPR_GAP_DOWN_THRESHOLD = 1

FIRST_CANDLE_PERCENT_THRESHOLD = 3.5

DAILY_OPEN = 0
DAILY_HIGH = 1
DAILY_LOW = 2
DAILY_CLOSE = 3
DAILY_VOLUME = 4

AVERAGE_VOLUME_THRESHOLD = 500
FIRST_CANDLE_VOLUME_THRESHOLD = 500

WICK_THRESHOLD = 1
TAIL_THRESHOLD = 1

MAX_QUANTITY = 15

CAP_UTILIZATION = .75

TRAIL_PERCENTAGE = 1.5


def calculate_pivots(high, low, close):
    central_pivot = (high + low + close) / 3
    bottom_pivot = (high + low) / 2
    top_pivot = 2 * central_pivot - bottom_pivot
    return (top_pivot, central_pivot, bottom_pivot)


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
            CPR, self.daily_data[1], self.daily_data[2], self.daily_data[3], 'central', scatter=True)
        self.pivots_bottom_daily = self.I(
            CPR, self.daily_data[1], self.daily_data[2], self.daily_data[3], 'bottom', scatter=True)
        print("Completed Initialization")
        self.daily_trigger = False
        self.price = 0
        self.trail = 0
        # self.ema63 = self.I(talib.EMA, close, 63)
        # self.pivots = self.I(CPR, self.data)
        # self.data_5min = self.data

    def next(self):

        time = self.data.index[-1].to_pydatetime().time()
        date = self.data.index[-1].to_pydatetime()
        current_candle_close = self.data.Close[-1]

        # Do not take trades after 12
        if self.position.size == 0 and time.hour >= 11 and time.minute >= 30:
            for order in self.orders:
                print(f"Cancelling order {order} as not triggered before time")
                order.cancel()
            return

        if self.position.is_long:
            stopPrice = self.data.Close[-1] * (100 - TRAIL_PERCENTAGE) / 100
            self.trail = max(stopPrice, self.trail)

            if self.data.Close[-1] <= self.trail:
                print("Trailing stoploss hit")
                self.position.close()

        if time.hour == 3 and time.minute == 15:
            for order in self.orders:
                print(f"Cancelling order {order} as market is closing")
                order.cancel()
            if self.position.size != 0:
                print("Sold as time up")
            self.position.close()

        # By default in current day we get previous day daily ohlcv, previous day cpr, current candle ohlcv
        CURRENT_INDEX = -1
        NUMBER_OF_BARS = 75

        current_day_pivot = (self.pivots_central_daily[CURRENT_INDEX],
                             self.pivots_top_daily[CURRENT_INDEX], self.pivots_bottom_daily[CURRENT_INDEX])  # This is calculated with previous day ohlc

        if (len(self.pivots_bottom_daily) < 151):
            # Skip testing 1st day as we don't have previous day pivot
            return

        current_ema = self.ema63_daily[CURRENT_INDEX]

        if (self.pivots_central_daily[-1] != self.pivots_central_daily[-2]):

            previousDayPivot = (self.pivots_central_daily[-NUMBER_OF_BARS],
                                self.pivots_top_daily[-NUMBER_OF_BARS], self.pivots_bottom_daily[-NUMBER_OF_BARS])
            isAscending = previousDayPivot[CPR_TOP] < current_day_pivot[CPR_BOTTOM]
            isDescending = previousDayPivot[CPR_BOTTOM] > current_day_pivot[CPR_TOP]
            isNotAdjacent = (current_day_pivot[CPR_BOTTOM] > previousDayPivot[CPR_TOP]) or (
                current_day_pivot[CPR_TOP] < previousDayPivot[CPR_BOTTOM])

            isNarrowCPR = abs(
                2 * (current_day_pivot[CPR_CENTRAL] - current_day_pivot[CPR_BOTTOM])) < (NARROW_THRESHOLD / 1000 * self.daily_data[DAILY_CLOSE][CURRENT_INDEX])

            prevDayAverageVolume = self.daily_data[DAILY_VOLUME][CURRENT_INDEX] / \
                NUMBER_OF_BARS

            FIRST5MCANDLE = -2  # As we are currently in 20th min candle

            YESTERDAYLASTCANDLE = -3

            bufferPrice = 0.50
            if self.data.Open[FIRST5MCANDLE] >= 50 and self.data.Open[FIRST5MCANDLE] <= 250:
                bufferPrice = 0.50
            elif self.data.Open[FIRST5MCANDLE] >= 251 and self.data.Open[FIRST5MCANDLE] <= 500:
                bufferPrice = 0.75
            elif self.data.Open[FIRST5MCANDLE] >= 501 and self.data.Open[FIRST5MCANDLE] <= 750:
                bufferPrice = 1.00
            elif self.data.Open[FIRST5MCANDLE] >= 751 and self.data.Open[FIRST5MCANDLE] <= 1000:
                bufferPrice = 1.25
            elif self.data.Open[FIRST5MCANDLE] >= 1001 and self.data.Open[FIRST5MCANDLE] <= 1250:
                bufferPrice = 2.50
            elif self.data.Open[FIRST5MCANDLE] >= 1251 and self.data.Open[FIRST5MCANDLE] <= 1500:
                bufferPrice = 3.00
            elif self.data.Open[FIRST5MCANDLE] >= 1501 and self.data.Open[FIRST5MCANDLE] <= 1750:
                bufferPrice = 4.00
            elif self.data.Open[FIRST5MCANDLE] >= 1751 and self.data.Open[FIRST5MCANDLE] <= 2000:
                bufferPrice = 4.50
            elif self.data.Open[FIRST5MCANDLE] >= 2001 and self.data.Open[FIRST5MCANDLE] <= 2500:
                bufferPrice = 5.00
            else:
                bufferPrice = 6.00

            isBullish = self.data.Close[FIRST5MCANDLE] >= self.data.Open[FIRST5MCANDLE]
            isBearish = self.data.Close[FIRST5MCANDLE] < self.data.Open[FIRST5MCANDLE]

            isEMAAboveCPR = self.ema63_daily[FIRST5MCANDLE] > current_day_pivot[CPR_TOP]

            hasAverageVolumeInPrevDay = prevDayAverageVolume > AVERAGE_VOLUME_THRESHOLD

            hasFirstCandleVolume = self.data.Volume[FIRST5MCANDLE] > FIRST_CANDLE_VOLUME_THRESHOLD

            isNotGapUp = ((abs(self.data.Close[YESTERDAYLASTCANDLE] - self.data.Open[FIRST5MCANDLE]) / (
                (self.data.Close[YESTERDAYLASTCANDLE] + self.data.Open[FIRST5MCANDLE]) / 2)) * 100) <= GAP_UP_THRESHOLD

            isNotGapUp = ((abs(self.data.Close[YESTERDAYLASTCANDLE] - self.data.Open[FIRST5MCANDLE]) / (
                (self.data.Close[YESTERDAYLASTCANDLE] + self.data.Open[FIRST5MCANDLE]) / 2)) * 100) <= GAP_DOWN_THRESHOLD

            isTodayAscending = isAscending and isNotAdjacent

            isTodayDescending = isDescending and isNotAdjacent

            isTodayAdjacent = not isNotAdjacent

            hasFirstCandleClosedAboveEMA = self.data.Close[FIRST5MCANDLE] >= self.ema63_daily[FIRST5MCANDLE]

            hasFirstCandleClosedBelowEMA = self.data.Close[FIRST5MCANDLE] <= self.ema63_daily[FIRST5MCANDLE]

            hasFirstCandleClosedAboveCPR = self.data.Close[FIRST5MCANDLE] >= current_day_pivot[CPR_TOP]

            hasFirstCandleClosedBelowCPR = self.data.Close[FIRST5MCANDLE] <= current_day_pivot[CPR_BOTTOM]

            hasFirstCandleOpenedAboveCPR = self.data.Open[FIRST5MCANDLE] >= current_day_pivot[CPR_BOTTOM]

            hasFirstCandleOpenedBelowCPR = self.data.Open[FIRST5MCANDLE] <= current_day_pivot[CPR_BOTTOM]

            isNotGapUpCPR = (abs(previousDayPivot[CPR_TOP] - current_day_pivot[CPR_BOTTOM]) / (
                (previousDayPivot[CPR_TOP] + current_day_pivot[CPR_BOTTOM]) / 2)) * 100 <= CPR_GAP_UP_THRESHOLD

            isNotGapDownCPR = (abs(previousDayPivot[CPR_TOP] - current_day_pivot[CPR_BOTTOM]) / (
                (previousDayPivot[CPR_TOP] + current_day_pivot[CPR_BOTTOM]) / 2)) * 100 <= CPR_GAP_UP_THRESHOLD

            hasFirstCandlePercentChange = (abs(self.data.Close[YESTERDAYLASTCANDLE] - self.data.Close[FIRST5MCANDLE]) / (
                (self.data.Close[YESTERDAYLASTCANDLE] + self.data.Close[FIRST5MCANDLE]) / 2)) * 100 <= FIRST_CANDLE_PERCENT_THRESHOLD

            hasNotPreviousDayWideCPR = abs(
                2 * (previousDayPivot[CPR_CENTRAL] - previousDayPivot[CPR_BOTTOM])) <= (WIDE_CPR_THRESHOLD / 1000 * self.daily_data[DAILY_CLOSE][CURRENT_INDEX - NUMBER_OF_BARS])

            hasNotLengthyWick = ((abs(self.data.High[FIRST5MCANDLE] - self.data.Close[FIRST5MCANDLE]) / (
                (self.data.High[FIRST5MCANDLE] + self.data.Close[FIRST5MCANDLE]) / 2)) * 100) <= WICK_THRESHOLD if isBullish else False

            hasNotLengthyTail = ((abs(self.data.Low[FIRST5MCANDLE] - self.data.Close[FIRST5MCANDLE]) / (
                (self.data.Low[FIRST5MCANDLE] + self.data.Close[FIRST5MCANDLE]) / 2)) * 100) <= TAIL_THRESHOLD if isBearish else False

            hasBullishGreaterBody = ((abs(self.data.Close[FIRST5MCANDLE] - self.data.Open[FIRST5MCANDLE]) / (
                (self.data.Close[FIRST5MCANDLE] + self.data.Open[FIRST5MCANDLE]) / 2)) * 100) > ((abs(self.data.High[FIRST5MCANDLE] - self.data.Close[FIRST5MCANDLE]) / (
                    (self.data.High[FIRST5MCANDLE] + self.data.Close[FIRST5MCANDLE]) / 2)) * 100) if isBullish else False

            hasBearishGreaterBody = ((abs(self.data.Close[FIRST5MCANDLE] - self.data.Open[FIRST5MCANDLE]) / (
                (self.data.Close[FIRST5MCANDLE] + self.data.Open[FIRST5MCANDLE]) / 2)) * 100) > ((abs(self.data.Low[FIRST5MCANDLE] - self.data.Close[FIRST5MCANDLE]) / (
                    (self.data.Low[FIRST5MCANDLE] + self.data.Close[FIRST5MCANDLE]) / 2)) * 100) if isBearish else False

            ascendingBuySign = isTodayAscending and isNarrowCPR and isNotGapUp and \
                isBullish and hasFirstCandleClosedAboveEMA and hasFirstCandleClosedAboveCPR and \
                hasFirstCandleOpenedAboveCPR and isNotGapUpCPR and hasAverageVolumeInPrevDay and \
                hasFirstCandleVolume and hasFirstCandlePercentChange and hasNotPreviousDayWideCPR and \
                hasNotLengthyWick and hasBullishGreaterBody

            if self.position.size == 0 and ascendingBuySign:
                amountCanBeUsed = self.equity * CAP_UTILIZATION
                amountPerTrade = amountCanBeUsed / MAX_QUANTITY
                self.price = self.data.High[FIRST5MCANDLE] + bufferPrice
                self.trail = current_day_pivot[CPR_BOTTOM]
                size = int(amountPerTrade / (4 * self.data.Close[-1]))
                self.buy(
                    stop=self.price, tag='AscendingLong1', size=(2 * size) or 1, tp=self.price * 1.015, sl=current_day_pivot[CPR_BOTTOM])
                self.buy(
                    stop=self.price, tag='AscendingLong2', size=size or 1, tp=self.price * 1.025, sl=current_day_pivot[CPR_BOTTOM])
                self.buy(
                    stop=self.price, tag='AscendingLong3', size=size or 1, tp=self.price * 1.035, sl=current_day_pivot[CPR_BOTTOM])
                print(f"Bought at price {self.data.High[FIRST5MCANDLE]}")
                # self.daily_trigger = False

            # descendingSellSign = isTodayDescending and isNarrowCPR and isNotGapUp and \
            #     isBullish and hasFirstCandleClosedAboveEMA and hasFirstCandleClosedAboveCPR and \
            #     hasFirstCandleOpenedAboveCPR and isNotGapUpCPR and hasAverageVolumeInPrevDay and \
            #     hasFirstCandleVolume and hasFirstCandlePercentChange and hasNotPreviousDayWideCPR and \
            #     hasNotLengthyWick and hasBullishGreaterBody

            # if ascendingBuySign:
            #     self.daily_trigger = True
            # else:
            #     self.daily_trigger = False

        # isPreviousCPRNarrow = (
        #     previousDayPivot[0] - previousDayPivot[2]) < previousDayPivot[0] * 0.003

        # Target
        # print(pivot, previousDayPivot, sep=":::")
        # if self.data.index[-1].to_pydatetime().date().month == 8 and self.data.index[-1].to_pydatetime().date().day == 1 and self.data.index[-1].to_pydatetime().date().year == 2022:
        #     breakpoint()

        # Day indicators
        # if self.daily_trigger:
        #     if self.position.size == 0:
        #         self.buy(
        #             stop=self.data.High[FIRST5MCANDLE], tag='AscendingLong')
        #         print("Bought")
        #         self.daily_trigger = False
        # if current_candle_close < current_day_pivot[2] and self.data.Close[-2] < current_day_pivot[2] and self.position.is_long:
        #     self.position.close()
        #     print("Sold as stop loss hit")
        # if time.hour == 15 and time.minute == 10:
        #     if self.position.size != 0:
        #         self.position.close()
        #         print("Sold as time up")


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
