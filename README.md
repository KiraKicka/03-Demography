<h1 align="center">Ru-EU Migration Retention Analyzer (DBNA Model)</h1>

<p align="center">
    <img src="https://img.shields.io/badge/Python-3.8+-blue.svg" alt="Python 3.8+">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT">
    <img src="https://img.shields.io/badge/Status-For%20Fun-purple" alt="Status: For Fun">
    <img src="https://img.shields.io/badge/Pandas-2.x-blue.svg" alt="Pandas">
    <img src="https://img.shields.io/badge/Matplotlib-3.x-orange.svg" alt="Matplotlib">
</p>

This project is a tool for demographic analysis of migration processes between Russia and the European Union countries. Instead of simply counting arrivals, it answers two questions:

1.  **Where do Russian migrants put down long-term roots — and via which track?** Settlement is split into **passport** (naturalization) vs. **permanent residence** (long-term permit holders).
2.  **Which countries have the highest exodus?** A cumulative **Outflow Rate** marks countries used mainly as transit points.

The analysis covers the key countries of attraction for Russian citizens (e.g. **Germany, Spain, France, Italy**, plus any other destinations present in your data) for the period since 2008.

## 📊 Methodology: DBNA (Demographic Balancing with Naturalization Adjustment)

Standard "inflow minus outflow" analysis does not work for EU migration statistics due to two problems:
1.  **Unreliable emigration data (`migr_emi`)**: Many countries, including France, hardly keep any records of foreigners who have left, so outflow cannot be measured directly.
2.  **Distortion due to naturalization (`migr_acq`)**: When an immigrant obtains citizenship, they disappear from the "foreign population" statistics, which a naive model misreads as emigration.

The **DBNA Method** reconstructs a theoretical population path from the starting stock and cumulative inflow, then explains the gap to the observed stock as either naturalization (integration) or implied emigration (loss).

### Key Metrics

All rates are expressed as a percentage of cumulative inflow over the period.

1.  **Total Retention Rate**:
    Share of the inflow cohort that physically remained — whether still on a permit or already naturalized.
    $$\text{Total Retention} = \frac{(P_{end} - P_{start}) + A}{I_{sum}} \times 100\%$$

2.  **Passport-Anchored Rate** (citizenship track):
    $$\text{Passport} = \frac{A}{I_{sum}} \times 100\%$$

3.  **Permit Retention Rate** (residence-permit track):
    Net change in the permit stock — those who stayed on a permit rather than naturalizing.
    $$\text{Permit} = \frac{P_{end} - P_{start}}{I_{sum}} \times 100\%$$

4.  **Outflow Rate** (exodus / transit intensity):
    $$\text{Outflow} = \frac{\max\left(0,\; (P_{start} + I_{sum}) - (P_{end} + A)\right)}{I_{sum}} \times 100\%$$

Where:
-   $P_{start}, P_{end}$: residence-permit stock at the start/end of the period (`migr_resvalid`).
-   $I_{sum}$: cumulative inflow over the period (`migr_resfirst`).
-   $A$: cumulative naturalizations (`migr_acq`).

> **The three outcome tracks form a clean partition of the inflow cohort:**
> $$\text{Passport} + \text{Permit} + \text{Outflow} = 100\%$$
> (since $\text{Total Retention} = \text{Passport} + \text{Permit}$, and $\text{Total Retention} + \text{Outflow} = 100\%$ before the outflow zero-clip). Each migrant is accounted for exactly once: naturalized, still on a permit, or gone.
>
> **Why not `migr_reslong`?** An earlier version measured the permit track from the long-term-residents stock. That stock also counts arrivals from *before* the analysis window, so dividing it by within-window inflow produced rates well over 100% (plus a coverage break for Germany at 2016 and a definitional inconsistency for Norway). Net permit change (`migr_resvalid`) is consistent with the inflow series and keeps the partition exact. `migr_reslong` is retained only as an overlay line in the per-country dashboard.
>
> **Note:** Permit Retention can be **negative** when a community shrinks on permits — e.g. when more people naturalize (moving to the passport track) or emigrate than arrive. This is a real signal, common post-2022.

## 💾 Data Acquisition & Setup

This analysis relies exclusively on official data from the **Eurostat Database**, ensuring reliability and comparability across countries. The script requires **4 specific datasets**.

1.  **Clone the repository and install dependencies:**
    ```bash
    git clone https://github.com/KiraKicka/Ru-EU-Migration-Retention-Analyzer
    cd Ru-EU-Migration-Retention-Analyzer
    pip install pandas numpy matplotlib seaborn openpyxl
    ```

2.  **Download the data from Eurostat:**
    Navigate to the [Eurostat Database](https://ec.europa.eu/eurostat/web/main/data/database) and download the following tables. For each table, use the **"Data Explorer"** to apply the filters below, then download the data as a **"Spreadsheet"** (`.xlsx` file).

    *   **Filters to apply for ALL tables:**
        *   **Citizen (CITIZEN):** Russia (RU)
        *   **Sex (SEX):** Total
        *   **Age (AGE):** Total
        *   **Unit (UNIT):** Person / Number
        *   **Destination (GEO):** Select your countries of interest (e.g., Germany, France, Italy, Spain).

    *   **Required Tables:**

        | Eurostat Code | Purpose | Why it's needed | Filename to use |
        | :--- | :--- | :--- | :--- |
        | **`migr_resvalid`** | Stock of Residents | Provides the baseline number of Russian citizens with valid residence permits at the end of each year. This is our ground truth ($P_{start}$, $P_{end}$). | `migr_resvalid.xlsx` |
        | **`migr_resfirst`** | Inflow of Immigrants | Tracks the number of newly issued first residence permits each year — the primary input ($I_{sum}$) and the denominator for every rate. | `migr_resfirst.xlsx` |
        | **`migr_acq`** | Naturalization | Accounts for residents who acquire citizenship ($A$). They haven't emigrated but are removed from the `migr_resvalid` stock, so tracking them avoids misreading their exit as a "loss" and feeds the Passport-Anchored Rate. | `migr_acq.xlsx` |
        | **`migr_reslong`** | Long-Term Residents | Long-term/permanent residents — shown as an overlay line in the per-country dashboard (not used in the headline metrics). | `migr_reslong.xlsx` |

    > **Note:** The script automatically handles Monthly data (e.g., `2023M12`) should any dataset contain it — it filters for December to align with annual stocks.

3.  **Place the files:**
    Move the downloaded `.xlsx` files into the root directory of the project, ensuring their names match the "Filename to use" column above.

## 📈 Understanding the Visualizations

The script opens **two windows**.

### 1. Migrant Tracks Over Time (three trend panels)

Three stacked panels — **Settled (Citizenship)**, **Settled (Residence permit, net)**, and **Left the country (Outflow)**. In each panel the X-axis is the year, the Y-axis is the rate as a **% of cumulative inflow** up to that year, and each line is a country. This shows how each track *evolves* rather than just its end-state, so you can watch a corridor harden into settlement or drift toward transit, with the `2014` and `2022` markers flagging geopolitical breaks. The three panels partition the inflow cohort (they sum to 100% per country-year), so reading across them tells the whole story of a corridor.

Because every rate is normalized to cumulative inflow, the lines are comparable across both countries and years. **Caveats:** the first year or two of a corridor has a small cumulative-inflow denominator, so early points can swing (a regularization can briefly push net permit retention slightly above 100%). The permit panel can also go **negative** when a community shrinks on permits (heavy naturalization or emigration). Years below a 1,000-person cumulative-inflow floor are dropped.

### 2. Per-Country Gap Decomposition (interactive time series)

Pick a country with the radio buttons to see the gap between a theoretical "perfect retention" path and the observed reality over time. The side panel shows that country's four metrics; the `2014` and `2022` markers flag geopolitical breaks.

*   **Lines:**
    *   <span style="color:grey">▬</span> **Grey (`Theoretical Max`):** residents if **no one left** and **no one naturalized** — `Initial Stock + Cumulative Inflow`.
    *   <span style="color:gold">▬</span> **Gold Dashed (`Theoretical Adj.`):** `Theoretical Max` minus cumulative naturalizations — the stock you'd expect if the only exit were acquiring a passport.
    *   <span style="color:#003366">▬</span> **Blue (`Official Stock`):** valid residence permits (`migr_resvalid`).
    *   <span style="color:#2ca02c">▬·</span> **Green Dash-Dot (`Long-Term Residents`):** permanent residents (`migr_reslong`).

*   **Shaded Areas:**
    *   <span style="color:gold;opacity:0.5">■</span> **Gold (`Naturalized / Integration`):** between grey and gold lines — the cohort that integrated by becoming citizens. A positive outcome, not a loss.
    *   <span style="color:red;opacity:0.5">■</span> **Red (`Implied Emigration`):** between the citizenship-adjusted line and the actual stock — the unexplained loss.

*   **Bottom Chart (Flows):**
    *   <span style="color:teal">▬</span> **Teal (`Inflow`):** new arrivals (First Permits).
    *   <span style="color:gold">▬</span> **Gold (`Naturalization`):** passport issuance. Comparing the two shows whether a country is importing new people or integrating existing ones.

## 🚀 Usage

To run the analysis, execute the script from the command line:

```bash
python migration_analysis.py
```

Execution process:
1.  **Console report**: Two ranking tables are printed to the terminal — long-term settlement (split by track) and exodus intensity.
    ```
    ==============================================================================
     DEMOGRAPHIC REPORT: RU -> EU MIGRATION RETENTION & EXODUS
    ==============================================================================

     LONG-TERM SETTLEMENT RANKING (by Total Retention):
    Country          | Total Retention |  of which Passport |    of which Permit
    ------------------------------------------------------------------------------
    France           |           93.8% |              42.3% |              51.5%
    Spain            |           70.7% |               9.5% |              61.2%
    Germany          |           69.9% |              36.1% |              33.8%
    Italy            |           57.0% |              29.5% |              27.5%

     EXODUS RANKING (by Outflow / transit intensity):
    Country          |    Outflow Rate
    ------------------------------------
    Italy            |           43.0%
    Germany          |           30.1%
    Spain            |           29.3%
    France           |            6.2%
    ==============================================================================
    ```
    (Numbers are illustrative; actual values depend on your downloaded data. Passport + Permit = Total Retention, and Total Retention + Outflow = 100%.)
2.  **Two windows** open automatically: the **Migrant Tracks Over Time** trend panels and the interactive **Per-Country Gap Decomposition** dashboard.

## 📄 License

This project is distributed under the MIT License.
