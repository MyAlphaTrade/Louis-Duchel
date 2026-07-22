// Indicator calculation functions — pure math, each returns an array
// aligned with the input bars (null for warmup periods).

export function sma(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values, period) {
  const out = new Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    if (i === period - 1) {
      let sum = 0;
      for (let j = 0; j < period; j++) sum += values[j];
      prev = sum / period;
      out[i] = prev;
    } else if (i >= period) {
      prev = values[i] * k + prev * (1 - k);
      out[i] = prev;
    }
  }
  return out;
}

export function rsi(values, period) {
  const out = new Array(values.length).fill(null);
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    if (i <= period) {
      avgGain += gain;
      avgLoss += loss;
      if (i === period) {
        avgGain /= period;
        avgLoss /= period;
        out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
      }
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }
  return out;
}

export function macd(values, fast, slow, signal) {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const macdLine = values.map((_, i) =>
    emaFast[i] !== null && emaSlow[i] !== null ? emaFast[i] - emaSlow[i] : null
  );
  const validMacd = macdLine.filter((v) => v !== null);
  const signalLine = new Array(values.length).fill(null);
  const k = 2 / (signal + 1);
  let prev = null;
  let firstValid = macdLine.findIndex((v) => v !== null);
  if (firstValid === -1) return { macdLine, signalLine, histogram: macdLine };
  for (let i = firstValid; i < values.length; i++) {
    if (i === firstValid + signal - 1) {
      let sum = 0;
      for (let j = firstValid; j <= i; j++) sum += macdLine[j];
      prev = sum / signal;
      signalLine[i] = prev;
    } else if (i >= firstValid + signal) {
      prev = macdLine[i] * k + prev * (1 - k);
      signalLine[i] = prev;
    }
  }
  const histogram = macdLine.map((v, i) =>
    v !== null && signalLine[i] !== null ? v - signalLine[i] : null
  );
  return { macdLine, signalLine, histogram };
}

export function atr(bars, period) {
  const tr = bars.map((b, i) => {
    if (i === 0) return b.high - b.low;
    const prevClose = bars[i - 1].close;
    return Math.max(
      b.high - b.low,
      Math.abs(b.high - prevClose),
      Math.abs(b.low - prevClose)
    );
  });
  return ema(tr, period);
}

export function bollinger(values, period, stdDev) {
  const mid = sma(values, period);
  const upper = new Array(values.length).fill(null);
  const lower = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    const mean = sum / period;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) variance += (values[j] - mean) ** 2;
    const sd = Math.sqrt(variance / period);
    upper[i] = mid[i] + sd * stdDev;
    lower[i] = mid[i] - sd * stdDev;
  }
  return { mid, upper, lower };
}

export function stochastic(bars, kPeriod, dPeriod, smooth) {
  const kRaw = bars.map((b, i) => {
    if (i < kPeriod - 1) return null;
    let highest = -Infinity;
    let lowest = Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      highest = Math.max(highest, bars[j].high);
      lowest = Math.min(lowest, bars[j].low);
    }
    return highest === lowest ? 50 : ((b.close - lowest) / (highest - lowest)) * 100;
  });
  // Smooth %K
  const k = sma(kRaw.map((v) => v ?? 0), smooth).map((v, i) => (kRaw[i] !== null ? v : null));
  const d = sma(k.map((v) => v ?? 0), dPeriod).map((v, i) => (k[i] !== null ? v : null));
  return { k, d };
}

export function adx(bars, period) {
  const plusDM = bars.map((_, i) => {
    if (i === 0) return 0;
    const up = bars[i].high - bars[i - 1].high;
    const down = bars[i - 1].low - bars[i].low;
    return up > down && up > 0 ? up : 0;
  });
  const minusDM = bars.map((_, i) => {
    if (i === 0) return 0;
    const down = bars[i - 1].low - bars[i].low;
    const up = bars[i].high - bars[i - 1].high;
    return down > up && down > 0 ? down : 0;
  });
  const tr = bars.map((b, i) => {
    if (i === 0) return b.high - b.low;
    const pc = bars[i - 1].close;
    return Math.max(b.high - b.low, Math.abs(b.high - pc), Math.abs(b.low - pc));
  });
  const atrArr = ema(tr, period);
  const plusDI = plusDM.map((v, i) =>
    atrArr[i] !== null ? (ema(plusDM, period)[i] / atrArr[i]) * 100 : null
  );
  const minusDI = minusDM.map((v, i) =>
    atrArr[i] !== null ? (ema(minusDM, period)[i] / atrArr[i]) * 100 : null
  );
  const dx = plusDM.map((_, i) => {
    if (plusDI[i] === null || minusDI[i] === null) return null;
    const sum = plusDI[i] + minusDI[i];
    return sum === 0 ? 0 : (Math.abs(plusDI[i] - minusDI[i]) / sum) * 100;
  });
  const adxArr = ema(dx.map((v) => v ?? 0), period).map((v, i) => (dx[i] !== null ? v : null));
  return adxArr;
}

// Compute a single indicator value series from bars + params
export function computeIndicator(indicatorId, params, bars) {
  const closes = bars.map((b) => b.close);
  switch (indicatorId) {
    case "ema": return ema(closes, params.period || 9);
    case "sma": return sma(closes, params.period || 20);
    case "rsi": return rsi(closes, params.period || 14);
    case "macd": {
      const { macdLine } = macd(closes, params.fast || 12, params.slow || 26, params.signal || 9);
      return macdLine;
    }
    case "macd_signal": {
      const { signalLine } = macd(closes, params.fast || 12, params.slow || 26, params.signal || 9);
      return signalLine;
    }
    case "atr": return atr(bars, params.period || 14);
    case "bollinger": {
      const { mid } = bollinger(closes, params.period || 20, params.std_dev || 2);
      return mid;
    }
    case "bollinger_upper": {
      const { upper } = bollinger(closes, params.period || 20, params.std_dev || 2);
      return upper;
    }
    case "bollinger_lower": {
      const { lower } = bollinger(closes, params.period || 20, params.std_dev || 2);
      return lower;
    }
    case "stochastic": {
      const { k } = stochastic(bars, params.k_period || 14, params.d_period || 3, params.smooth || 3);
      return k;
    }
    case "stochastic_d": {
      const { d } = stochastic(bars, params.k_period || 14, params.d_period || 3, params.smooth || 3);
      return d;
    }
    case "adx": return adx(bars, params.period || 14);
    case "volume": return sma(bars.map((b) => b.volume || 0), params.ma_period || 20);
    case "price": return closes;
    case "breakout": {
      const lookback = params.lookback || 20;
      return closes.map((_, i) => {
        if (i < lookback) return null;
        let hi = -Infinity;
        for (let j = i - lookback; j < i; j++) hi = Math.max(hi, bars[j].high);
        return hi;
      });
    }
    case "breakout_low": {
      const lookback = params.lookback || 20;
      return closes.map((_, i) => {
        if (i < lookback) return null;
        let lo = Infinity;
        for (let j = i - lookback; j < i; j++) lo = Math.min(lo, bars[j].low);
        return lo;
      });
    }
    case "support_resistance": {
      const lookback = params.lookback || 50;
      return sma(closes, lookback);
    }
    default: return closes;
  }
}