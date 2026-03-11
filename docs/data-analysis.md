# Data Analysis

The data analysis module (`lib/analytics/data_analyzer.py`) provides statistical analysis and technical scanning tools for market data. These functions operate on stored bar data without running backtests, making them useful for market research, strategy idea generation, and universe screening.

## Statistical Analysis

### Return Distribution Analysis

Computes log-return statistics and tests for normality:

```python
from analytics.data_analyzer import return_distribution

stats = return_distribution(bars_df, period=1)
```

**Parameters:**
- `bars_df`: DataFrame with a `close` column.
- `period`: Return period. `1` = bar-to-bar returns, `5` = weekly returns on daily data, etc.

**Returns a dictionary:**

| Key | Description |
|-----|-------------|
| `mean` | Mean log-return |
| `std` | Standard deviation of log-returns |
| `skewness` | Skewness. Negative = more frequent large losses. Positive = more frequent large gains. |
| `kurtosis` | Excess kurtosis. Positive = fat tails (more extreme events than normal). Zero = normal distribution. |
| `jb_statistic` | Jarque-Bera test statistic |
| `jb_pvalue` | Jarque-Bera p-value. Below 0.05 = reject normality at 95% confidence. |
| `n_returns` | Number of return observations |

**Interpreting results:**
- Most financial assets have negative skewness and positive kurtosis (fat tails).
- A Jarque-Bera p-value below 0.05 means returns are not normally distributed, which is typical for financial data and important for risk model selection.

### Volatility Analysis

Computes realized volatility at multiple rolling windows:

```python
from analytics.data_analyzer import volatility_analysis

vol = volatility_analysis(bars_df)
```

**Returns:**

| Key | Description |
|-----|-------------|
| `realized_vol` | Annualized realized volatility (standard deviation of log-returns * sqrt(252)) |
| `rolling_vols` | Dictionary of rolling volatility series at windows of 5, 10, 21, and 63 bars, each annualized |
| `vol_of_vol` | Volatility of the 21-bar rolling volatility -- measures how stable/unstable volatility is |

The rolling windows correspond to roughly 1 week, 2 weeks, 1 month, and 1 quarter of trading days. Each rolling series is annualized by multiplying by sqrt(252).

High vol-of-vol indicates regime-switching behavior where calm and volatile periods alternate.

### Autocorrelation Analysis

Computes autocorrelation functions for returns and squared returns:

```python
from analytics.data_analyzer import autocorrelation_analysis

acf = autocorrelation_analysis(bars_df, max_lag=20)
```

**Returns:**

| Key | Description |
|-----|-------------|
| `acf_returns` | List of autocorrelation values at lags 1 through `max_lag` for raw returns |
| `acf_squared` | List of autocorrelation values at lags 1 through `max_lag` for squared returns |

**Interpreting results:**
- **Negative ACF at lag 1** in returns suggests mean-reversion tendency -- useful for mean-reversion strategies.
- **Positive ACF at lag 1** in returns suggests momentum -- useful for trend-following strategies.
- **Significant ACF in squared returns** (volatility clustering) is nearly universal in financial data and means that large moves tend to follow large moves regardless of direction.

### Tail Risk Metrics

Computes Value at Risk and Conditional VaR at multiple confidence levels:

```python
from analytics.data_analyzer import tail_risk_analysis

tail = tail_risk_analysis(bars_df)
```

**Returns:**

| Key | Description |
|-----|-------------|
| `var_95` | 95% VaR (5th percentile of log-returns). The daily loss exceeded only 5% of the time. |
| `cvar_95` | 95% CVaR (mean of returns in the worst 5%). Average loss on the worst days. |
| `var_99` | 99% VaR (1st percentile of log-returns) |
| `cvar_99` | 99% CVaR (mean of returns in the worst 1%) |

These are expressed as log-returns (negative values represent losses). For example, `var_95 = -0.03` means there is a 5% chance of losing more than 3% in a single bar.

### Correlation Analysis

#### Cross-Asset Correlation Matrix

```python
from analytics.data_analyzer import correlation_matrix

# Pass a dict of symbol -> DataFrame (each with a 'close' column)
corr = correlation_matrix({
    "BTC/USD": btc_bars_df,
    "ETH/USD": eth_bars_df,
    "SOL/USD": sol_bars_df,
})
# Returns a pandas DataFrame correlation matrix
```

Correlation is computed on log-returns. High correlation between assets reduces diversification benefit. Low or negative correlation is useful for portfolio construction.

#### Rolling Correlation

```python
from analytics.data_analyzer import rolling_correlation

roll_corr = rolling_correlation(bars_a, bars_b, window=30)
# Returns a numpy array of rolling correlation values
```

Rolling correlation reveals whether the relationship between two assets is stable or time-varying. If rolling correlation varies widely, static correlation is misleading.

### Regime Detection

Hidden Markov Model-based regime detection:

```python
from analytics.data_analyzer import regime_detection

regimes = regime_detection(bars_df, n_regimes=2)
```

**Returns:**

| Key | Description |
|-----|-------------|
| `regimes` | List of regime labels (integers) for each return observation |
| `transition_matrix` | Matrix of probabilities of transitioning between regimes |
| `regime_stats` | Per-regime statistics: mean return, std, count, fraction of time spent |

Requires the `hmmlearn` package. Two regimes typically correspond to low-volatility (calm) and high-volatility (turbulent) periods. The transition matrix shows how likely the market is to switch between regimes.

## Technical Scanning

### Indicator Scanning

Compute a batch of technical indicators over a bar series:

```python
from analytics.data_analyzer import scan_indicators

ind_df = scan_indicators(bars_df, indicators=None)  # None = all default indicators
```

The DataFrame `bars_df` must have columns: `open`, `high`, `low`, `close`, `volume`.

**Default indicators when `indicators=None`:**

| Indicator | Column(s) | Description |
|-----------|-----------|-------------|
| `sma_10` | `sma_10` | 10-period Simple Moving Average |
| `sma_30` | `sma_30` | 30-period Simple Moving Average |
| `ema_10` | `ema_10` | 10-period Exponential Moving Average |
| `ema_30` | `ema_30` | 30-period Exponential Moving Average |
| `rsi_14` | `rsi_14` | 14-period Relative Strength Index |
| `macd` | `macd_line`, `macd_signal`, `macd_histogram` | MACD (12, 26, 9) |
| `bollinger` | `bb_upper`, `bb_middle`, `bb_lower` | Bollinger Bands (20, 2) |
| `atr_14` | `atr_14` | 14-period Average True Range |
| `stochastic` | `stoch_k`, `stoch_d` | Stochastic Oscillator |
| `obv` | `obv` | On-Balance Volume |

You can request specific indicators by passing a list:

```python
ind_df = scan_indicators(bars_df, indicators=["sma_10", "rsi_14", "macd"])
```

Custom periods are supported via the naming convention:

```python
ind_df = scan_indicators(bars_df, indicators=["sma_50", "ema_200", "rsi_7", "atr_20"])
```

### Signal Detection

Detect buy/sell signals from indicator crossovers:

```python
from analytics.data_analyzer import scan_signals

signals = scan_signals(bars_df, signal_configs=[
    {"type": "crossover", "fast": "ema_10", "slow": "sma_30"},
    {"type": "crossover", "fast": "sma_10", "slow": "sma_30"},
])
```

Each signal config defines the detection rule. Currently supported:
- `"crossover"`: Generates a `BUY` signal when the `fast` indicator crosses above the `slow` indicator, and a `SELL` signal on the opposite crossover.

**Returned signal events:**

```python
[
    {
        "index": 45,           # Bar index where signal occurred
        "signal": "BUY",       # "BUY" or "SELL"
        "type": "crossover",
        "strength": 12.5,      # Absolute difference between fast and slow at crossover
        "fast": "ema_10",
        "slow": "sma_30",
    },
    ...
]
```

### Candlestick Pattern Recognition

Detect common candlestick patterns:

```python
from analytics.data_analyzer import scan_patterns

patterns = scan_patterns(bars_df)
```

**Detected patterns:**

| Pattern | Description | Strength |
|---------|-------------|----------|
| `doji` | Body less than 10% of the full bar range | `1 - body_ratio` |
| `hammer` | Small body at top, lower shadow > 2x body, small upper shadow | `lower_shadow / full_range` |
| `bullish_engulfing` | Current bullish bar fully engulfs previous bearish bar | `body / full_range` |
| `bearish_engulfing` | Current bearish bar fully engulfs previous bullish bar | `body / full_range` |

### Support and Resistance Levels

Identify key price levels:

```python
from analytics.data_analyzer import support_resistance

levels = support_resistance(bars_df, method="clustering", n_levels=5)
# Returns: sorted list of price levels, e.g. [41200.0, 42000.0, 42800.0, 43500.0, 44100.0]
```

**Methods:**
- `"clustering"` (default): Uses k-means clustering on highs, lows, and closes to find natural price clusters. Requires `scipy`.
- `"pivot"`: Classic pivot point calculation `(H + L + C) / 3`, sampled evenly to return `n_levels` levels.

## Universe Scanning

Scan multiple symbols for signals and rank them:

```python
from analytics.data_analyzer import scan_universe

results = scan_universe(
    store=market_data_store,        # MarketDataStore instance
    exchange="kraken",
    symbols=["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"],
    timeframe="1h",
    scan_config=[
        {"type": "crossover", "fast": "ema_10", "slow": "sma_30"},
    ],
)
# Returns: {"BTC/USD": [signal_events], "ETH/USD": [signal_events], ...}
# Only symbols with at least one signal are included.
```

This reads bars from the `MarketDataStore` for each symbol, runs `scan_signals()`, and collects results. Symbols with no detected signals are omitted from the output. Use this to find which assets currently have active signals across your universe.

## Visualization

View analysis results in the web dashboard at `/analysis`. See the [Dashboard Guide](dashboard.md) for details.
