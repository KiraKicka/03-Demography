import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.widgets import RadioButtons
import os
from functools import reduce

# ==========================================
# CONFIGURATION & STYLE
# ==========================================
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)

# Only the 4 datasets actually used by the two-question model:
#   1) Long-term settlement, split by track (passport vs. permanent residence)
#   2) Exodus / transit intensity (cumulative outflow)
FILES = {
    'stock': 'migr_resvalid.xlsx',        # Valid residence permits (ground-truth stock)
    'inflow': 'migr_resfirst.xlsx',       # First permits issued (inflow)
    'naturalization': 'migr_acq.xlsx',    # Citizenship acquisitions (passport track)
    'long_term': 'migr_reslong.xlsx',     # Long-term residents (permanent-residence track)
}

# ==========================================
# STEP 1: DATA LOADING & CLEANING
# ==========================================
def load_and_process_file(filepath, value_name):
    """
    Loads an Eurostat spreadsheet, cleans it with vectorized operations,
    and melts it into Long Format.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    # Load data
    # Column 0 is Country, Columns 1..N are Years
    df = pd.read_excel(filepath)

    # Rename first column to 'Country' for consistency
    df.rename(columns={df.columns[0]: 'Country'}, inplace=True)

    # Handle Monthly Data (e.g., 2008M12): keep December as the year-end value
    data_cols = df.columns[1:]
    if any('M' in str(c) for c in data_cols):
        m12_cols = [c for c in data_cols if str(c).endswith('M12')]
        df = df[['Country'] + m12_cols]
        df.columns = ['Country'] + [str(c).replace('M12', '') for c in m12_cols]

    # Melt: Turn Year columns into rows
    year_cols = df.columns[1:]
    df_melted = df.melt(id_vars=['Country'], value_vars=year_cols,
                        var_name='Year', value_name=value_name)

    # Vectorized Cleaning
    # 1. Replace Eurostat ':' (not available) with NaN
    # 2. Convert to numeric (coercing any errors to NaN)
    df_melted[value_name] = pd.to_numeric(
        df_melted[value_name].replace(':', np.nan),
        errors='coerce'
    )

    # Clean Year (ensure it's integer, handling potential string headers)
    df_melted['Year'] = pd.to_numeric(df_melted['Year'], errors='coerce').astype('Int64')

    # Drop rows where Year parsing failed (if any)
    df_melted = df_melted.dropna(subset=['Year'])

    return df_melted

# ==========================================
# STEP 2: CALCULATION LOGIC
# ==========================================
def calculate_theoretical_reconstruction(g):
    """
    Reconstructs the theoretical population path for the time-series view:
      - Theoretical_Max: nobody leaves, nobody naturalizes (Base + cumulative inflow)
      - Theoretical_Adj: nobody leaves, but some naturalize (Max - cumulative naturalization)
    The gap between Theoretical_Adj and the actual Stock is the implied emigration.
    """
    g = g.sort_values('Year')
    valid_stock = g['Stock'].dropna()
    if valid_stock.empty:
        g['Theoretical_Max'] = np.nan
        g['Theoretical_Adj'] = np.nan
        return g

    start_year = g.loc[valid_stock.index[0], 'Year']
    base_stock = valid_stock.iloc[0]

    # Cumulative flows ONLY after the base year
    mask = g['Year'] > start_year
    inflow_cum = g['Inflow'].fillna(0).where(mask, 0).cumsum()
    nat_cum = g['Naturalization'].fillna(0).where(mask, 0).cumsum()

    g['Theoretical_Max'] = base_stock + inflow_cum
    g['Theoretical_Adj'] = g['Theoretical_Max'] - nat_cum

    return g

def process_data():
    """
    Loads, merges, filters, and reconstructs the theoretical population path.
    """
    print("Loading data...")
    data_frames = [
        load_and_process_file(FILES['stock'], 'Stock'),
        load_and_process_file(FILES['inflow'], 'Inflow'),
        load_and_process_file(FILES['naturalization'], 'Naturalization'),
        load_and_process_file(FILES['long_term'], 'LongTerm'),
    ]

    # Merge all datasets
    print("Merging and processing...")
    df = reduce(lambda left, right: pd.merge(left, right, on=['Country', 'Year'], how='outer'),
                data_frames)

    # Filter Timeframe (Year >= 2008)
    df = df[df['Year'] >= 2008]

    # Interpolate single-year gaps only.
    # Stock: do NOT fillna(0) so the dynamic start year is preserved.
    df['Stock'] = df.groupby('Country')['Stock'].transform(
        lambda x: x.interpolate(method='linear', limit=1)
    )

    # LongTerm: interpolate single gaps but leave genuine missingness as NaN.
    # Used only for the long-term-residents overlay line in the per-country dashboard.
    df['LongTerm'] = df.groupby('Country')['LongTerm'].transform(
        lambda x: x.interpolate(method='linear', limit=1)
    )

    # Reconstruct theoretical path (used by the interactive time-series view)
    cols = ['Year', 'Stock', 'Inflow', 'Naturalization', 'LongTerm']
    df = df.groupby('Country', group_keys=True)[cols].apply(calculate_theoretical_reconstruction)
    df = df.reset_index(level='Country')

    return df

# ==========================================
# STEP 2.5: DEMOGRAPHIC METRICS
# ==========================================
def calculate_demographic_metrics(df):
    """
    Per-country demographic indicators aggregated over the full available period.

    Inputs (per country):
        Stock_Start, Stock_End : first/last valid residence-permit stock
        Sum_Inflow             : cumulative first permits over the period
        Sum_Acq                : cumulative naturalizations over the period

    Indicators (% of cumulative inflow):
        Total_Retention_Rate   = (Stock_End - Stock_Start + Sum_Acq) / Sum_Inflow
        Passport_Anchored_Rate = Sum_Acq / Sum_Inflow                  (settled via citizenship)
        Permit_Retention_Rate  = (Stock_End - Stock_Start) / Sum_Inflow (settled on a permit)
        Outflow_Rate           = max(0, Theoretical_Max - (Stock_End + Sum_Acq)) / Sum_Inflow

    These form a clean partition of the inflow cohort:
        Passport_Anchored_Rate + Permit_Retention_Rate + Outflow_Rate = 100%
    (Total_Retention = Passport + Permit; Total_Retention + Outflow = 100%, before the
    outflow zero-clip). migr_reslong is no longer used here; it survives only as the
    long-term-residents overlay line in the per-country dashboard.
    """
    results = []
    for country, group in df.groupby('Country'):
        group = group.sort_values('Year')
        valid_stock = group['Stock'].dropna()

        if valid_stock.empty:
            continue

        start_val = valid_stock.iloc[0]
        end_val = valid_stock.iloc[-1]

        start_year = group.loc[valid_stock.index[0], 'Year']
        end_year = group.loc[valid_stock.index[-1], 'Year']

        # Sum flows over the period where stock exists (exclude the base year itself)
        period_mask = (group['Year'] > start_year) & (group['Year'] <= end_year)
        sum_inflow = group.loc[period_mask, 'Inflow'].sum()
        sum_nat = group.loc[period_mask, 'Naturalization'].sum()

        if sum_inflow < 1000:  # Filter noise / statistically trivial corridors
            continue

        delta_stock = end_val - start_val
        theoretical_max = start_val + sum_inflow

        # Total retention: net stock change plus those who left the foreign-stock via passport
        total_retention = ((delta_stock + sum_nat) / sum_inflow) * 100

        # Track 1: passport (naturalization) settlement
        passport_anchored = (sum_nat / sum_inflow) * 100

        # Track 2: net residence-permit retention (those who stayed on a permit rather
        # than naturalizing). Bounded and commensurable with inflow; together with the
        # passport track it sums to Total Retention.
        permit_retention = (delta_stock / sum_inflow) * 100

        # Exodus / transit intensity. Clip at 0 to absorb legalization/amnesty anomalies
        # (actual stock exceeding the theoretical maximum).
        implied_outflow = theoretical_max - (end_val + sum_nat)
        outflow_rate = (max(0.0, implied_outflow) / sum_inflow) * 100

        results.append({
            'Country': country,
            'Start_Year': int(start_year),
            'End_Year': int(end_year),
            'Total_Retention_Rate': total_retention,
            'Passport_Anchored_Rate': passport_anchored,
            'Permit_Retention_Rate': permit_retention,
            'Outflow_Rate': outflow_rate,
        })

    return pd.DataFrame(results)

def calculate_yearly_metrics(df, min_cum_inflow=1000):
    """
    Per-country, per-year version of the demographic indicators, for trend plotting.

    For each year t after a country's base year, every rate is normalized to the
    inflow accumulated from the base year up to t (I_cum), so the lines are
    comparable across both countries and time:

        Passport_Anchored_Rate(t) = A_cum(t) / I_cum(t)
        Permit_Retention_Rate(t)  = (P(t) - P_start) / I_cum(t)
        Outflow_Rate(t)           = max(0, (P_start + I_cum(t)) - (P(t) + A_cum(t))) / I_cum(t)
        Total_Retention_Rate(t)   = (P(t) - P_start + A_cum(t)) / I_cum(t)

    Passport + Permit + Outflow sum to 100% (before the outflow zero-clip). Years where
    I_cum is below `min_cum_inflow` are dropped: with a tiny denominator the rates swing
    wildly and are not meaningful.
    """
    rows = []
    for country, group in df.groupby('Country'):
        group = group.sort_values('Year')
        valid_stock = group['Stock'].dropna()
        if valid_stock.empty:
            continue

        start_year = group.loc[valid_stock.index[0], 'Year']
        start_val = valid_stock.iloc[0]

        sub = group[group['Year'] >= start_year].copy()
        after_base = sub['Year'] > start_year
        sub['I_cum'] = sub['Inflow'].fillna(0).where(after_base, 0).cumsum()
        sub['A_cum'] = sub['Naturalization'].fillna(0).where(after_base, 0).cumsum()

        for _, r in sub.iterrows():
            i_cum = r['I_cum']
            p_t = r['Stock']
            if i_cum < min_cum_inflow or pd.isna(p_t):
                continue

            a_cum = r['A_cum']
            theoretical_max = start_val + i_cum

            rows.append({
                'Country': country,
                'Year': int(r['Year']),
                'Total_Retention_Rate': (p_t - start_val + a_cum) / i_cum * 100,
                'Passport_Anchored_Rate': a_cum / i_cum * 100,
                'Permit_Retention_Rate': (p_t - start_val) / i_cum * 100,
                'Outflow_Rate': max(0.0, theoretical_max - (p_t + a_cum)) / i_cum * 100,
            })

    return pd.DataFrame(rows)

# ==========================================
# STEP 2.6: CONSOLE REPORTING
# ==========================================
def _fmt_pct(value):
    """Format a percentage, rendering NaN as 'N/A'."""
    return f"{value:.1f}%" if pd.notna(value) else "N/A"

def print_demographic_report(metrics_df):
    """
    Prints two ranking tables:
      1. Long-term settlement (Total Retention, split into passport vs. long-term residence)
      2. Exodus intensity (Outflow Rate)
    """
    if metrics_df.empty:
        print("\nNo countries passed the data/noise filters - nothing to report.\n")
        return

    print("\n" + "=" * 78)
    print(" DEMOGRAPHIC REPORT: RU -> EU MIGRATION RETENTION & EXODUS")
    print("=" * 78)

    # --- Table 1: where migrants settle long-term -----------------------------
    print("\n LONG-TERM SETTLEMENT RANKING (by Total Retention):")
    print(f"{'Country':<16} | {'Total Retention':>15} | {'of which Passport':>18} | {'of which Permit':>18}")
    print("-" * 78)
    settled = metrics_df.sort_values('Total_Retention_Rate', ascending=False)
    for _, row in settled.iterrows():
        print(f"{row['Country']:<16} | "
              f"{_fmt_pct(row['Total_Retention_Rate']):>15} | "
              f"{_fmt_pct(row['Passport_Anchored_Rate']):>18} | "
              f"{_fmt_pct(row['Permit_Retention_Rate']):>18}")

    # --- Table 2: where migrants leave from -----------------------------------
    print("\n EXODUS RANKING (by Outflow / transit intensity):")
    print(f"{'Country':<16} | {'Outflow Rate':>15}")
    print("-" * 36)
    outflow = metrics_df.sort_values('Outflow_Rate', ascending=False)
    for _, row in outflow.iterrows():
        print(f"{row['Country']:<16} | {_fmt_pct(row['Outflow_Rate']):>15}")

    print("=" * 78 + "\n")

# ==========================================
# STEP 3: VISUALIZATION (YEARLY TRENDS)
# ==========================================
def plot_yearly_trends(yearly_df):
    """
    Three stacked time-series panels (one per indicator). In each panel:
    X = year, Y = % of cumulative inflow, one line per country.
    Lets you read how each migrant track evolves over time across countries.
    """
    if yearly_df.empty:
        return None

    panels = [
        ('Passport_Anchored_Rate', 'Settled — Citizenship (passport track)'),
        ('Permit_Retention_Rate', 'Settled — Residence permit (net retention)'),
        ('Outflow_Rate', 'Left the country — Outflow / transit'),
    ]

    countries = sorted(yearly_df['Country'].unique())
    cmap = plt.get_cmap('tab10' if len(countries) <= 10 else 'tab20')
    colors = {c: cmap(i % cmap.N) for i, c in enumerate(countries)}

    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(12, 12))
    fig.canvas.manager.set_window_title('Migrant Tracks Over Time')

    for ax, (col, title) in zip(axes, panels):
        for country in countries:
            d = yearly_df[yearly_df['Country'] == country].sort_values('Year')
            ax.plot(d['Year'], d[col], marker='o', markersize=3, linewidth=1.8,
                    color=colors[country], label=country)
        ax.set_title(title, fontweight='bold')
        ax.set_ylabel('% of cumulative inflow')
        ax.grid(True, linestyle=':', alpha=0.6)
        for year in (2014, 2022):
            ax.axvline(x=year, color='black', linestyle=':', alpha=0.4)

    axes[-1].set_xlabel('Year')

    # Single shared legend on the right
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='center right', title='Country', frameon=True)

    fig.suptitle('Migrant tracks over time (% of cumulative inflow)',
                 fontsize=15, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 0.86, 0.97])  # room for legend + suptitle
    return fig

# ==========================================
# STEP 3.5: VISUALIZATION (PER-COUNTRY TIME SERIES)
# ==========================================
def plot_gap_decomposition(ax_main, ax_bottom, country, df):
    """
    Renders the per-country gap decomposition (stock vs. theoretical path) over time.
    """
    data = df[df['Country'] == country].sort_values('Year')

    if data.empty or data['Stock'].isna().all():
        ax_main.clear()
        ax_main.text(0.5, 0.5, f"Insufficient data for {country}",
                     ha='center', va='center', transform=ax_main.transAxes)
        ax_bottom.clear()
        ax_bottom.axis('off')
        return

    ax_main.clear()
    ax_bottom.clear()
    ax_bottom.axis('on')

    years = data['Year']

    # --- MAIN PLOT (Stock & Gap) ---
    ax_main.plot(years, data['Theoretical_Max'], color='grey', linewidth=1.5,
                 label='Theoretical Max (Zero Exit)')
    ax_main.plot(years, data['Theoretical_Adj'], color='gold', linestyle='--', linewidth=2,
                 label='Theoretical (Citizenship Adj.)')
    ax_main.plot(years, data['Stock'], color='#003366', linewidth=2,
                 label='Official Resident Stock')
    ax_main.plot(years, data['LongTerm'], color='#2ca02c', linewidth=1.5, linestyle='-.',
                 label='Long-Term Residents')

    # Area 1: Naturalized (Integration) - Gold Fill
    ax_main.fill_between(years, data['Theoretical_Max'], data['Theoretical_Adj'],
                         color='gold', alpha=0.2, label='Naturalized (Integration)')

    # Area 2: Implied Emigration (Loss) - Red Fill (gap between citizenship-adj line and actual stock)
    ax_main.fill_between(years, data['Theoretical_Adj'], data['Stock'],
                         where=(data['Theoretical_Adj'] > data['Stock']),
                         color='tab:red', alpha=0.3, label='Implied Emigration')

    # Annotations (Geopolitical Events)
    for year in [2014, 2022]:
        if year in years.values:
            ax_main.axvline(x=year, color='black', linestyle=':', alpha=0.6)
            y_max = ax_main.get_ylim()[1]
            ax_main.text(year, y_max * 0.95, f' {year}', rotation=90, va='top')
            ax_bottom.axvline(x=year, color='black', linestyle=':', alpha=0.6)

    ax_main.set_title(f'Migration Gap Decomposition: {country}', fontsize=16, fontweight='bold')
    ax_main.set_ylabel('Population Stock', fontsize=12)
    ax_main.yaxis.set_label_position("right")
    ax_main.yaxis.tick_right()
    ax_main.legend(loc='upper left', frameon=True)
    ax_main.grid(True, linestyle=':', alpha=0.6)
    plt.setp(ax_main.get_xticklabels(), visible=False)

    # --- BOTTOM PLOT (Flows) ---
    ax_bottom.plot(years, data['Inflow'], color='teal', linewidth=2, label='Inflow (First Permits)')
    ax_bottom.plot(years, data['Naturalization'], color='gold', linewidth=2,
                   label='Naturalization (Passports)')

    max_val = data[['Inflow', 'Naturalization']].max().max()
    if not pd.isna(max_val) and max_val > 0:
        ax_bottom.set_ylim(bottom=0, top=max_val * 1.1)

    ax_bottom.set_ylabel('Annual Flows', fontsize=12)
    ax_bottom.yaxis.set_label_position("right")
    ax_bottom.yaxis.tick_right()
    ax_bottom.set_xlabel('Year', fontsize=12)
    ax_bottom.legend(loc='upper left', frameon=True)
    ax_bottom.grid(True, linestyle=':', alpha=0.6)

def build_interactive_dashboard(df, metrics_df):
    """
    Builds the interactive per-country dashboard (radio selector + stats panel).
    Returns the figure (caller is responsible for plt.show()).
    """
    valid_countries = (df.dropna(subset=['Stock'])
                         .groupby('Country')['Stock'].max()
                         .sort_values(ascending=False)
                         .index.tolist())
    if not valid_countries:
        return None

    top_countries = valid_countries[:15]

    fig = plt.figure()
    fig.canvas.manager.set_window_title('Per-Country Gap Decomposition')
    gs = fig.add_gridspec(4, 1)
    ax_main = fig.add_subplot(gs[0:3, :])
    ax_bottom = fig.add_subplot(gs[3, :], sharex=ax_main)

    plt.subplots_adjust(left=0.3)  # Room for sidebar

    rax = plt.axes([0.02, 0.2, 0.25, 0.6], facecolor='#f0f0f0')
    radio = RadioButtons(rax, top_countries)

    stats_ax = plt.axes([0.02, 0.05, 0.25, 0.15], facecolor='#f0f0f0')
    stats_ax.axis('off')

    def update(label):
        plot_gap_decomposition(ax_main, ax_bottom, label, df)

        stats_ax.clear()
        stats_ax.axis('off')

        country_stats = metrics_df[metrics_df['Country'] == label]
        if not country_stats.empty:
            row = country_stats.iloc[0]
            text_str = (f"Metrics for {label}:\n\n"
                        f"Total Retention: {_fmt_pct(row['Total_Retention_Rate'])}\n"
                        f"  Passport:      {_fmt_pct(row['Passport_Anchored_Rate'])}\n"
                        f"  Permit (net):  {_fmt_pct(row['Permit_Retention_Rate'])}\n"
                        f"Outflow:         {_fmt_pct(row['Outflow_Rate'])}")
        else:
            text_str = f"Metrics for {label}:\nN/A"

        stats_ax.text(0.05, 0.9, text_str, transform=stats_ax.transAxes,
                      fontsize=10, verticalalignment='top', fontfamily='monospace')
        fig.canvas.draw_idle()

    radio.on_clicked(update)
    update(top_countries[0])

    # Keep the widget alive (prevent garbage collection)
    fig._radio_widget = radio
    return fig

# ==========================================
# MAIN
# ==========================================
def main():
    try:
        df = process_data()

        metrics_df = calculate_demographic_metrics(df)

        # Console analytical report (the two rankings)
        print_demographic_report(metrics_df)

        if metrics_df.empty:
            print("No valid data found - skipping dashboards.")
            return

        print("Starting dashboards... check the popup windows.")

        # View 1: per-year trend lines (one panel per indicator, one line per country)
        yearly_df = calculate_yearly_metrics(df)
        plot_yearly_trends(yearly_df)

        # View 2: interactive per-country time series
        build_interactive_dashboard(df, metrics_df)

        plt.show()

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
