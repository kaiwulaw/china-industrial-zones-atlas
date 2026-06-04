#!/usr/bin/env python3
"""
China Industrial Development Zones — An Interactive Atlas
=========================================================

COMP 4433 · Project 2 · Kai Wu

An *explanatory* Dash application built on a research-grade spatial dataset of
China's nationally and provincially approved industrial development zones
(2018 NDRC consolidated catalog), geocoded and enriched with satellite-derived
covariates.

The app answers two linked questions through direct user interaction:

  TAB 1  "Where do China's zones go — and why?"
         A placement explorer. Filter the 2,543 zones by province, type,
         approval level, and approval year, and watch where they sit on the
         map, how a chosen geographic/economic covariate is distributed in
         your selection versus the national baseline, and how the approval
         wave unfolded over time.

  TAB 2  "How do zone-hosting counties differ from the rest?"
         A comparison lab over 2,420 GADM admin-3 counties. Set the threshold
         that defines a "zone county," pick a statistic, and read the
         standardized mean difference (Cohen's d) between zone and non-zone
         counties live — a standardized zone-vs-non-zone comparison, interactive.

Run locally:
    pip install -r requirements.txt
    python app.py
    # open http://127.0.0.1:8050  in a browser

Figure-building is factored into pure functions (fig_* and the stats helpers)
so the analytical logic can be unit-tested without launching the server.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from dash import Dash, dcc, html, callback, Input, Output

# ============================================================
# DESIGN TOKENS  —  "cartographic atlas" editorial palette
# ============================================================

PAPER      = "#F3EEE3"   # warm paper background
PANEL      = "#FBF8F1"   # raised panel / plot background
INK        = "#211E1A"   # primary text
MUTED      = "#6B6358"   # secondary text
LINE       = "#DAD2C2"   # gridlines, hairlines
TEAL       = "#1E6E64"   # water / coast / zone "HIGHER" in the effect chart
TEAL_DEEP  = "#14534B"
TERRA      = "#B9532E"   # land / zone "LOWER" in the effect chart
TERRA_SOFT = "#CB6A45"
GOLD       = "#C2922E"
INDIGO     = "#2F4B6E"

# Approval-level colors
LEVEL_COLORS = {"State Council": INDIGO, "Provincial": GOLD}

# Sequential colorscale for the placement map (paper -> terracotta)
SEQ_SCALE = [[0.0, "#EBD9C2"], [0.45, GOLD], [1.0, TERRA]]

FONT_UI   = "Archivo, 'Helvetica Neue', Arial, sans-serif"
FONT_HEAD = "Fraunces, Georgia, 'Times New Roman', serif"

# ---- Plotly template -------------------------------------------------------
pio.templates["atlas"] = go.layout.Template(
    layout=dict(
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font=dict(family=FONT_UI, color=INK, size=13),
        title=dict(font=dict(family=FONT_HEAD, size=17, color=INK), x=0.01, xanchor="left"),
        margin=dict(l=58, r=24, t=54, b=48),
        xaxis=dict(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE, ticks="outside",
                   tickcolor=LINE, title=dict(font=dict(size=12, color=MUTED))),
        yaxis=dict(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE, ticks="outside",
                   tickcolor=LINE, title=dict(font=dict(size=12, color=MUTED))),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        colorway=[TEAL, TERRA, INDIGO, GOLD, TEAL_DEEP, TERRA_SOFT],
    )
)
pio.templates.default = "atlas"

GEO_STYLE = dict(
    scope="asia",
    projection_type="natural earth",
    showland=True, landcolor="#EDE6D6",
    showocean=True, oceancolor="#E3E7E4",
    showcountries=True, countrycolor="#C9BFAD",
    showcoastlines=True, coastlinecolor="#B6AD9B",
    showlakes=True, lakecolor="#E3E7E4",
    lataxis_range=[16, 54], lonaxis_range=[72, 136],
    bgcolor="rgba(0,0,0,0)",
)


# ============================================================
# DATA
# ============================================================

DATA_DIR = (Path(__file__).resolve().parent if "__file__" in globals()
            else Path.cwd()) / "data"

ZONE_TYPE_EN = {
    "经济开发区": "Economic Dev. Zone", "工业园区": "Industrial Park",
    "高新技术产业开发区": "High-Tech Zone", "经济技术开发区": "Econ. & Tech. Dev. Zone",
    "海关特殊监管区域": "Customs Special Zone", "其他类型开发区": "Other",
    "边境/跨境经济合作区": "Border / Cross-border",
}
APPROVAL_EN = {"国务院": "State Council", "省政府": "Provincial"}
PROVINCE_EN = {
    "上海市": "Shanghai", "云南省": "Yunnan", "内蒙古自治区": "Inner Mongolia",
    "北京市": "Beijing", "吉林省": "Jilin", "四川省": "Sichuan", "天津市": "Tianjin",
    "宁夏回族自治区": "Ningxia", "安徽省": "Anhui", "山东省": "Shandong",
    "山西省": "Shanxi", "广东省": "Guangdong", "广西壮族自治区": "Guangxi",
    "新疆维吾尔自治区": "Xinjiang", "江苏省": "Jiangsu", "江西省": "Jiangxi",
    "河北省": "Hebei", "河南省": "Henan", "浙江省": "Zhejiang", "海南省": "Hainan",
    "湖北省": "Hubei", "湖南省": "Hunan", "甘肃省": "Gansu", "福建省": "Fujian",
    "西藏自治区": "Tibet", "贵州省": "Guizhou", "辽宁省": "Liaoning",
    "重庆市": "Chongqing", "陕西省": "Shaanxi", "青海省": "Qinghai",
    "黑龙江省": "Heilongjiang",
}

# Tab-1 covariates (zone level)  —  (column, label, unit, log?)
ZONE_COVARS = {
    "dist_to_coast_km":            ("Distance to coast", "km", True),
    "pop_density_buffer_mean":     ("Population density (5 km buffer mean)", "persons", True),
    "built_2020_buffer_mean":      ("Built-up area 2020 (5 km buffer mean)", "m²", True),
    "forest_treecover2000_buffer_mean": ("Forest tree cover 2000 (5 km buffer mean)", "%", False),
    "核准面积_公顷":                 ("Approved zone area", "hectares", True),
}

# Tab-2 covariates (county level)  —  the five compared characteristics
COUNTY_COVARS = {
    "dist_to_coastal_port_km": ("Distance to coastal port", "km"),
    "dist_to_coast_km":        ("Distance to coast", "km"),
    "nightlights_2023":        ("Night lights, 2023", "nW/cm²/sr"),
    "pop_density_buffer_sum":  ("Population in 5 km buffer", "persons"),
    "built_2020_buffer_mean":  ("Built-up area 2020 (5 km buffer mean)", "m²"),
}


# Built-up snapshot years available in both datasets (GHS-BUILT-S R2023A)
SNAP_YEARS = [1990, 2000, 2010, 2015, 2020]

# Approval-year cohorts for the event study
COHORTS = ["≤1999", "2000–2009", "2010–2018"]
COHORT_COLORS = {"≤1999": INDIGO, "2000–2009": GOLD, "2010–2018": TERRA}


def cohort_bucket(y):
    return "≤1999" if y <= 1999 else ("2000–2009" if y <= 2009 else "2010–2018")


def _extract_year(s):
    if pd.isna(s):
        return np.nan
    s = str(s).strip()
    for sep in [".", "-", "/", " "]:
        if sep in s:
            s = s.split(sep)[0]
            break
    try:
        y = int(s)
        return y if 1980 <= y <= 2025 else np.nan
    except ValueError:
        return np.nan


def load_data():
    """Load and prepare the zone-level and county-level frames."""
    z = pd.read_csv(DATA_DIR / "enriched.csv", encoding="utf-8-sig")
    z["year"] = z["批准时间"].apply(_extract_year)
    z = z.dropna(subset=["year"])
    z["year"] = z["year"].astype(int)
    z["zone_type_en"] = z["开发区类型"].map(ZONE_TYPE_EN).fillna("Other")
    z["level_en"] = z["批准级别"].map(APPROVAL_EN).fillna("Provincial")
    z["province_en"] = z["省份"].map(PROVINCE_EN).fillna(z["省份"])
    z = z.rename(columns={"纬度_WGS84": "lat", "经度_WGS84": "lon", "开发区名称": "zone_name"})
    z = z.dropna(subset=["lat", "lon"])
    z["cohort"] = z["year"].apply(cohort_bucket)

    # Pre/post built-up (buffer mean) anchored to the snapshot nearest the
    # approval year — derived transparently from the five GHS-BUILT snapshots
    # so everything stays on one scale. Pre = latest snapshot <= approval
    # (else earliest); Post = earliest snapshot > approval (else latest).
    snap_cols = {y: f"built_{y}_buffer_mean" for y in SNAP_YEARS}

    def pick(row, post):
        yrs = [y for y in SNAP_YEARS if (y > row["year"]) == post]
        if not yrs:
            yrs = SNAP_YEARS
        chosen = min(yrs, key=lambda y: abs(y - row["year"]))
        return row[snap_cols[chosen]]

    z["built_pre"] = z.apply(lambda r: pick(r, post=False), axis=1)
    z["built_post"] = z.apply(lambda r: pick(r, post=True), axis=1)

    c = pd.read_csv(DATA_DIR / "analysis_units.csv", encoding="utf-8-sig")
    c = c.rename(columns={"latitude_wgs84": "lat", "longitude_wgs84": "lon"})
    return z, c


ZONES, COUNTIES = load_data()
YEAR_MIN, YEAR_MAX = int(ZONES["year"].min()), int(ZONES["year"].max())
PROV_OPTS = sorted(ZONES["province_en"].unique())
TYPE_OPTS = sorted(ZONES["zone_type_en"].unique())
COUNTY_PROV_OPTS = sorted(COUNTIES["province_name_1"].dropna().unique())

# Non-zone county built-up baseline (mean buffer-mean by snapshot year) —
# the secular-urbanization reference for the event-study tab.
_NONZONE = COUNTIES[COUNTIES["has_zone"] == 0]
NONZONE_BASELINE = {y: _NONZONE[f"built_{y}_buffer_mean"].mean() for y in SNAP_YEARS}


# ============================================================
# STATISTICS HELPERS  (pure)
# ============================================================

def standardized_mean_difference(a, b):
    """Cohen's d: (mean_a - mean_b) / pooled SD. NaNs dropped."""
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a) < 2 or len(b) < 2:
        return np.nan
    vp = ((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2)
    return (a.mean() - b.mean()) / np.sqrt(vp) if vp > 0 else np.nan


def effect_label(smd):
    m = abs(smd)
    if np.isnan(m):
        return "n/a"
    if m >= 0.8:
        return "large"
    if m >= 0.5:
        return "medium"
    if m >= 0.2:
        return "small"
    return "negligible"


def build_comparison(county_df, threshold, provinces=None):
    """Per-covariate comparison of zone (n_zones >= threshold) vs non-zone counties."""
    d = county_df
    if provinces:
        d = d[d["province_name_1"].isin(provinces)]
    z = d[d["n_zones"] >= threshold]
    n = d[d["n_zones"] < threshold]
    rows = []
    for col, (label, unit) in COUNTY_COVARS.items():
        a, b = z[col], n[col]
        rows.append({
            "column": col, "label": label, "unit": unit,
            "n_zone": int(a.notna().sum()), "n_nonzone": int(b.notna().sum()),
            "mean_zone": a.mean(), "mean_nonzone": b.mean(),
            "median_zone": a.median(), "median_nonzone": b.median(),
            "diff_in_means": a.mean() - b.mean(),
            "diff_in_medians": a.median() - b.median(),
            "smd": standardized_mean_difference(a, b),
        })
    return pd.DataFrame(rows)


# ============================================================
# TAB 1 FIGURES  (pure)
# ============================================================

def filter_zones(provinces, types, level, year_range):
    d = ZONES
    if provinces:
        d = d[d["province_en"].isin(provinces)]
    if types:
        d = d[d["zone_type_en"].isin(types)]
    if level and level != "All":
        d = d[d["level_en"] == level]
    d = d[(d["year"] >= year_range[0]) & (d["year"] <= year_range[1])]
    return d


def fig_zone_map(dff, color_col):
    label, unit, _ = ZONE_COVARS[color_col]
    fig = go.Figure()
    if len(dff):
        cval = dff[color_col]
        fig.add_trace(go.Scattergeo(
            lat=dff["lat"], lon=dff["lon"], mode="markers",
            marker=dict(size=5, color=cval, colorscale=SEQ_SCALE, opacity=0.78,
                        line=dict(width=0.3, color="rgba(33,30,26,0.4)"),
                        colorbar=dict(title=dict(text=f"{label}<br>({unit})", side="right"),
                                      thickness=12, len=0.7, x=1.0)),
            text=dff["zone_name"],
            customdata=np.stack([dff["province_en"], dff["zone_type_en"], dff["year"]], axis=-1),
            hovertemplate=("<b>%{text}</b><br>%{customdata[0]} · %{customdata[1]}"
                           "<br>Approved %{customdata[2]}<br>"
                           f"{label}: " + "%{marker.color:,.1f} " + unit + "<extra></extra>"),
        ))
    fig.update_geos(**GEO_STYLE)
    fig.update_layout(title=f"Zone locations, shaded by {label.lower()}",
                      margin=dict(l=8, r=8, t=46, b=8), height=520)
    return fig


def fig_covariate_distribution(dff, color_col):
    label, unit, use_log = ZONE_COVARS[color_col]
    full = ZONES[color_col].dropna()
    sel = dff[color_col].dropna()
    plot_full = np.log10(full.clip(lower=1e-2)) if use_log else full
    plot_sel = np.log10(sel.clip(lower=1e-2)) if use_log else sel
    axis_title = f"log₁₀ {label} ({unit})" if use_log else f"{label} ({unit})"

    fig = go.Figure()
    fig.add_trace(go.Histogram(x=plot_full, name="All zones (national)", histnorm="probability density",
                               marker_color=LINE, opacity=0.85, nbinsx=40))
    if len(plot_sel):
        fig.add_trace(go.Histogram(x=plot_sel, name="Your selection", histnorm="probability density",
                                   marker_color=TEAL, opacity=0.62, nbinsx=40))
        med = sel.median()
        med_plot = np.log10(max(med, 1e-2)) if use_log else med
        fig.add_vline(x=med_plot, line_dash="dash", line_color=TERRA, line_width=2,
                      annotation_text=f" selection median: {med:,.0f} {unit}",
                      annotation_position="top right",
                      annotation_font=dict(color=TERRA, size=11))
    nat_med = full.median()
    nat_plot = np.log10(max(nat_med, 1e-2)) if use_log else nat_med
    fig.add_vline(x=nat_plot, line_dash="dot", line_color=MUTED, line_width=1.5,
                  annotation_text=f" national median: {nat_med:,.0f} {unit}",
                  annotation_position="bottom right",
                  annotation_font=dict(color=MUTED, size=11))
    fig.update_layout(title=f"Distribution of {label.lower()}: selection vs national",
                      barmode="overlay", xaxis_title=axis_title, yaxis_title="density",
                      height=360, legend=dict(orientation="h", y=1.08, x=0))
    return fig


def fig_approvals_timeline(dff):
    if not len(dff):
        fig = go.Figure()
        fig.update_layout(title="Approvals by year", height=300,
                          annotations=[dict(text="No zones match the current filters",
                                            showarrow=False, font=dict(color=MUTED, size=14))])
        return fig
    yrs = list(range(YEAR_MIN, YEAR_MAX + 1))
    fig = go.Figure()
    for lvl in ["Provincial", "State Council"]:
        counts = (dff[dff["level_en"] == lvl].groupby("year").size()
                  .reindex(yrs, fill_value=0))
        fig.add_trace(go.Bar(x=yrs, y=counts.values, name=lvl,
                             marker_color=LEVEL_COLORS[lvl],
                             hovertemplate="%{x}: %{y} zones<extra>" + lvl + "</extra>"))
    fig.update_layout(title="Approvals by year, by approval level", barmode="stack",
                      xaxis_title="Approval year", yaxis_title="Zones approved",
                      height=300, legend=dict(orientation="h", y=1.12, x=0),
                      bargap=0.08)
    return fig


# ============================================================
# TAB 2 FIGURES  (pure)
# ============================================================

def fig_county_map(threshold, provinces):
    d = COUNTIES
    if provinces:
        d = d[d["province_name_1"].isin(provinces)]
    zone = d[d["n_zones"] >= threshold]
    non = d[d["n_zones"] < threshold]
    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lat=non["lat"], lon=non["lon"], mode="markers", name="Non-zone county",
        marker=dict(size=3.4, color="#B6AD9B", opacity=0.5),
        hovertext=non["county_name_3"], hoverinfo="text"))
    fig.add_trace(go.Scattergeo(
        lat=zone["lat"], lon=zone["lon"], mode="markers", name="Zone county",
        marker=dict(size=5.2, color=TEAL, opacity=0.82,
                    line=dict(width=0.4, color=TEAL_DEEP)),
        customdata=np.stack([zone["county_name_3"], zone["n_zones"]], axis=-1),
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} zone(s)<extra></extra>"))
    fig.update_geos(**GEO_STYLE)
    fig.update_layout(title=f"Counties hosting ≥ {threshold} zone(s) vs the rest",
                      margin=dict(l=8, r=8, t=46, b=8), height=520,
                      legend=dict(orientation="h", y=0.02, x=0.02,
                                  bgcolor="rgba(251,248,241,0.7)"))
    return fig


def fig_smd_bars(stats_df, statistic, selected_col):
    if statistic == "smd":
        vals, title, xlab = stats_df["smd"], ("Standardized mean difference "
            "(Cohen's d): zone vs non-zone"), "SMD  (negative = zone counties lower)"
    elif statistic == "mean":
        vals, title, xlab = stats_df["diff_in_means"], "Difference in means: zone − non-zone", "Difference in means"
    else:
        vals, title, xlab = stats_df["diff_in_medians"], "Difference in medians: zone − non-zone", "Difference in medians"

    labels = stats_df["label"]
    colors = [TEAL if v >= 0 else TERRA for v in vals]
    line_w = [3 if c == selected_col else 0 for c in stats_df["column"]]
    text = [f"{v:+.2f}" if statistic == "smd" else f"{v:+,.0f}" for v in vals]

    fig = go.Figure(go.Bar(
        y=labels, x=vals, orientation="h", marker_color=colors,
        marker_line_color=INK, marker_line_width=line_w,
        text=text, textposition="outside", textfont=dict(size=12),
        hovertemplate="%{y}<br>%{x:.3f}<extra></extra>"))
    fig.add_vline(x=0, line_color=INK, line_width=1)
    if statistic == "smd":
        for thr in (0.2, 0.5, 0.8):
            for s in (1, -1):
                fig.add_vline(x=s * thr, line_dash="dot", line_color=MUTED, line_width=1)
        fig.add_annotation(x=0.8, y=1.06, yref="paper", text="large", showarrow=False,
                           font=dict(color=MUTED, size=10))
        fig.add_annotation(x=0.5, y=1.06, yref="paper", text="medium", showarrow=False,
                           font=dict(color=MUTED, size=10))
        fig.add_annotation(x=0.2, y=1.06, yref="paper", text="small", showarrow=False,
                           font=dict(color=MUTED, size=10))
    fig.update_layout(title=title, xaxis_title=xlab, height=360,
                      yaxis=dict(autorange="reversed", automargin=True),
                      margin=dict(l=180, r=44, t=64, b=48))
    return fig


def fig_group_distributions(threshold, provinces, selected_col, log_on):
    d = COUNTIES
    if provinces:
        d = d[d["province_name_1"].isin(provinces)]
    label, unit = COUNTY_COVARS[selected_col]
    zone = d.loc[d["n_zones"] >= threshold, selected_col].dropna()
    non = d.loc[d["n_zones"] < threshold, selected_col].dropna()

    def t(x):
        return np.log10(x.clip(lower=1e-2)) if log_on else x
    axis_title = f"log₁₀ {label} ({unit})" if log_on else f"{label} ({unit})"

    fig = go.Figure()
    fig.add_trace(go.Violin(y=t(non), name="Non-zone", line_color=TERRA, fillcolor="rgba(185,83,46,0.18)",
                            box_visible=True, meanline_visible=True, points=False, side="negative",
                            x0="counties"))
    fig.add_trace(go.Violin(y=t(zone), name="Zone", line_color=TEAL, fillcolor="rgba(30,110,100,0.20)",
                            box_visible=True, meanline_visible=True, points=False, side="positive",
                            x0="counties"))
    fig.update_traces(width=0.9)
    fig.update_layout(title=f"{label}: zone vs non-zone counties",
                      yaxis_title=axis_title, violinmode="overlay", height=360,
                      legend=dict(orientation="h", y=1.1, x=0))
    return fig


# ============================================================
# TAB 3 FIGURES  —  designation event study (pure)
# ============================================================

TAU_BINS = [-30, -20, -10, -5, 0, 5, 10, 20, 30]
TAU_MIDS = [-25, -15, -7.5, -2.5, 2.5, 7.5, 15, 25]


def _zone_subset(cohorts, types, level):
    d = ZONES
    if cohorts:
        d = d[d["cohort"].isin(cohorts)]
    if types:
        d = d[d["zone_type_en"].isin(types)]
    if level and level != "All":
        d = d[d["level_en"] == level]
    return d


def _event_long(dff):
    """Long form: one row per (zone, snapshot) with event time tau."""
    parts = []
    for sy in SNAP_YEARS:
        parts.append(pd.DataFrame({
            "tau": sy - dff["year"], "built": dff[f"built_{sy}_buffer_mean"],
            "cohort": dff["cohort"].values, "snap": sy}))
    L = pd.concat(parts).dropna(subset=["built"])
    return L[(L["tau"] >= -30) & (L["tau"] <= 30)]


def fig_event_study(dff, cohorts, norm):
    """Median built-up by event-time bin, one line per cohort. tau=0 = designation."""
    L = _event_long(dff)
    L["tbin"] = pd.cut(L["tau"], bins=TAU_BINS, labels=TAU_MIDS, right=True)
    fig = go.Figure()
    series = [("All", L, INK)] + [(ch, L[L["cohort"] == ch], COHORT_COLORS[ch])
                                  for ch in COHORTS if (not cohorts or ch in cohorts)]
    for name, sub, col in series:
        if not len(sub):
            continue
        g = sub.groupby("tbin", observed=True)["built"]
        med = g.median()
        x = [float(m) for m in med.index]
        y = med.values.astype(float)
        if norm == "index":
            base = sub.loc[sub["tau"] <= 0, "built"].median()
            y = 100.0 * y / base if base and not np.isnan(base) else y
        elif norm == "log":
            y = np.log10(np.clip(y, 1, None))
        dash = "solid" if name != "All" else "dot"
        width = 3 if name != "All" else 2
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name=name,
                                 line=dict(color=col, width=width, dash=dash),
                                 marker=dict(size=7),
                                 hovertemplate="event year %{x:+.0f}<br>%{y:,.0f}<extra>" + name + "</extra>"))
    fig.add_vline(x=0, line_color=TERRA, line_width=1.5, line_dash="dash",
                  annotation_text=" designation (τ=0)", annotation_position="top",
                  annotation_font=dict(color=TERRA, size=11))
    ylab = {"raw": "Median built-up (m², 5 km buffer mean)",
            "index": "Built-up, indexed (pre-designation = 100)",
            "log": "log₁₀ median built-up (m²)"}[norm]
    fig.update_layout(title="Event study: built-up area around designation",
                      xaxis_title="Years relative to designation (τ)", yaxis_title=ylab,
                      height=380, legend=dict(orientation="h", y=1.12, x=0))
    return fig


def fig_treated_vs_baseline(dff, show_baseline):
    """Treated zones vs never-treated counties, mean built-up over calendar years."""
    treated = [dff[f"built_{y}_buffer_mean"].mean() for y in SNAP_YEARS]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=SNAP_YEARS, y=treated, mode="lines+markers", name="Zone (treated)",
                             line=dict(color=TEAL, width=3), marker=dict(size=8),
                             hovertemplate="%{x}: %{y:,.0f} m²<extra>treated</extra>"))
    if show_baseline:
        base = [NONZONE_BASELINE[y] for y in SNAP_YEARS]
        fig.add_trace(go.Scatter(x=SNAP_YEARS, y=base, mode="lines+markers", name="Non-zone county (baseline)",
                                 line=dict(color=MUTED, width=2, dash="dash"), marker=dict(size=7),
                                 hovertemplate="%{x}: %{y:,.0f} m²<extra>non-zone</extra>"))
        fig.add_annotation(x=1990, y=treated[0], text="already higher at baseline →",
                           showarrow=False, xanchor="left", yanchor="bottom",
                           font=dict(color=MUTED, size=10))
    fig.update_layout(title="Selection check: treated zones vs non-zone urbanization trend",
                      xaxis_title="Calendar year", yaxis_title="Mean built-up (m², 5 km buffer)",
                      height=330, legend=dict(orientation="h", y=1.14, x=0))
    return fig


def fig_prepost_scatter(dff, log_on):
    pre, post = dff["built_pre"], dff["built_post"]
    fig = go.Figure()
    for ch in COHORTS:
        m = dff["cohort"] == ch
        if not m.any():
            continue
        x = np.log10(pre[m].clip(lower=1)) if log_on else pre[m]
        y = np.log10(post[m].clip(lower=1)) if log_on else post[m]
        fig.add_trace(go.Scatter(x=x, y=y, mode="markers", name=ch,
                                 marker=dict(size=5, color=COHORT_COLORS[ch], opacity=0.5),
                                 hoverinfo="skip"))
    lo = float(np.log10(max(dff["built_pre"].min(), 1))) if log_on else float(dff["built_pre"].min())
    hi = float(np.log10(max(dff["built_post"].max(), 1))) if log_on else float(dff["built_post"].max())
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="no change (45°)",
                             line=dict(color=INK, width=1, dash="dot"), hoverinfo="skip"))
    ax = "log₁₀ built-up" if log_on else "built-up (m²)"
    fig.update_layout(title="Pre vs post designation (points above the line grew)",
                      xaxis_title=f"Pre-designation {ax}", yaxis_title=f"Post-designation {ax}",
                      height=330, legend=dict(orientation="h", y=1.14, x=0))
    return fig


# ============================================================
# LAYOUT
# ============================================================

app = Dash(__name__, title="China Industrial Zones — Atlas",
           assets_folder=str(DATA_DIR.parent / "assets"))
server = app.server  # for gunicorn / deployment

CONTROL = {"marginBottom": "18px"}
LABEL = {"fontWeight": 600, "fontSize": "13px", "color": INK, "display": "block", "marginBottom": "6px"}


def control_panel_tab1():
    return html.Div(className="panel controls", children=[
        html.H3("Filter the zones", className="panel-title"),
        html.Div(style=CONTROL, children=[
            html.Label("Province", style=LABEL),
            dcc.Dropdown(id="t1-province", options=[{"label": p, "value": p} for p in PROV_OPTS],
                         multi=True, placeholder="All provinces"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Zone type", style=LABEL),
            dcc.Dropdown(id="t1-type", options=[{"label": t, "value": t} for t in TYPE_OPTS],
                         multi=True, placeholder="All zone types"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Approval level", style=LABEL),
            dcc.RadioItems(id="t1-level", className="radio-row",
                           options=["All", "State Council", "Provincial"], value="All"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Approval year", style=LABEL),
            dcc.RangeSlider(id="t1-years", min=YEAR_MIN, max=YEAR_MAX, step=1,
                            value=[YEAR_MIN, YEAR_MAX],
                            marks={y: str(y) for y in range(1985, YEAR_MAX + 1, 5)},
                            tooltip={"placement": "bottom", "always_visible": False}),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Map / distribution covariate", style=LABEL),
            dcc.Dropdown(id="t1-covar", clearable=False,
                         options=[{"label": v[0], "value": k} for k, v in ZONE_COVARS.items()],
                         value="dist_to_coast_km"),
        ]),
        html.Div(id="t1-readout", className="readout"),
    ])


def control_panel_tab2():
    return html.Div(className="panel controls", children=[
        html.H3("Define the comparison", className="panel-title"),
        html.Div(style=CONTROL, children=[
            html.Label("A “zone county” hosts at least…", style=LABEL),
            dcc.Slider(id="t2-threshold", min=1, max=5, step=1, value=1,
                       marks={i: f"{i}" for i in range(1, 6)}),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Statistic shown in the effect chart", style=LABEL),
            dcc.RadioItems(id="t2-stat", className="radio-col",
                           options=[{"label": "Standardized mean difference (Cohen's d)", "value": "smd"},
                                    {"label": "Difference in means", "value": "mean"},
                                    {"label": "Difference in medians", "value": "median"}],
                           value="smd"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Highlight / distribution covariate", style=LABEL),
            dcc.Dropdown(id="t2-covar", clearable=False,
                         options=[{"label": v[0], "value": k} for k, v in COUNTY_COVARS.items()],
                         value="dist_to_coastal_port_km"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Restrict to provinces (optional)", style=LABEL),
            dcc.Dropdown(id="t2-province", options=[{"label": p, "value": p} for p in COUNTY_PROV_OPTS],
                         multi=True, placeholder="All provinces"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Distribution axis scale", style=LABEL),
            dcc.RadioItems(id="t2-log", className="radio-row",
                           options=[{"label": "linear", "value": "lin"},
                                    {"label": "log₁₀", "value": "log"}], value="log"),
        ]),
        html.Div(id="t2-readout", className="readout"),
    ])


def control_panel_tab3():
    return html.Div(className="panel controls", children=[
        html.H3("Event-study controls", className="panel-title"),
        html.Div(style=CONTROL, children=[
            html.Label("Approval cohorts", style=LABEL),
            dcc.Checklist(id="t3-cohorts", className="radio-col",
                          options=[{"label": c, "value": c} for c in COHORTS],
                          value=list(COHORTS)),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Zone type", style=LABEL),
            dcc.Dropdown(id="t3-type", options=[{"label": t, "value": t} for t in TYPE_OPTS],
                         multi=True, placeholder="All zone types"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Approval level", style=LABEL),
            dcc.RadioItems(id="t3-level", className="radio-row",
                           options=["All", "State Council", "Provincial"], value="All"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Event-study y-axis", style=LABEL),
            dcc.RadioItems(id="t3-norm", className="radio-col",
                           options=[{"label": "raw built-up (m²)", "value": "raw"},
                                    {"label": "indexed (pre-designation = 100)", "value": "index"},
                                    {"label": "log₁₀", "value": "log"}], value="index"),
        ]),
        html.Div(style=CONTROL, children=[
            html.Label("Reference layers", style=LABEL),
            dcc.Checklist(id="t3-extras", className="radio-col",
                          options=[{"label": "show non-zone county baseline", "value": "baseline"},
                                   {"label": "log axes on pre/post scatter", "value": "logscatter"}],
                          value=["baseline", "logscatter"]),
        ]),
        html.Div(id="t3-readout", className="readout"),
    ])


app.layout = html.Div(className="app-root", children=[
    html.Header(className="masthead", children=[
        html.Div(className="kicker", children="COMP 4433 · PROJECT 2 · SPATIAL POLICY DATA"),
        html.H1("China's Industrial Development Zones", className="title"),
        html.P(className="standfirst", children=[
            "An interactive atlas of the 2,543 nationally and provincially approved development zones "
            "in the 2018 NDRC consolidated catalog, geocoded and enriched with satellite-derived "
            "covariates. Three views: ", html.B("where zones sit and why"), ", ",
            html.B("how zone-hosting counties differ"), ", and ",
            html.B("whether the ground moved after designation"), ".",
        ]),
    ]),

    dcc.Tabs(id="tabs", value="placement", className="tabs", children=[
        dcc.Tab(label="1 · Placement Explorer", value="placement", className="tab", selected_className="tab--sel"),
        dcc.Tab(label="2 · Zone vs Non-Zone Comparator", value="compare", className="tab", selected_className="tab--sel"),
        dcc.Tab(label="3 · Designation Event Study", value="eventstudy", className="tab", selected_className="tab--sel"),
    ]),

    html.Div(id="tab-content", className="tab-content"),

    html.Footer(className="colophon", children=[
        html.P([html.B("Data. "),
                "Zones: China Development Zones Review Announcement (2018 ed.), NDRC-led inter-ministerial "
                "catalog; geocoded via AMap (GCJ-02 → WGS-84), four-stage QC. County units: GADM v4.1 "
                "admin-3 (N = 2,420). Covariates: GHS-BUILT R2023A, WorldPop 2020, EOG VIIRS, "
                "Natural Earth, MOT 2004 port catalog."]),
        html.P([html.B("Note. "),
                "This is a descriptive tool. Zone placement is endogenous — authorities select counties "
                "on observed and unobserved potential — so the differences shown reflect selection, not "
                "an estimated causal effect of designation. Built by Kai Wu."]),
    ]),
])


# ============================================================
# CALLBACKS
# ============================================================

@callback(Output("tab-content", "children"), Input("tabs", "value"))
def render_tab(tab):
    if tab == "placement":
        return html.Div(className="grid", children=[
            control_panel_tab1(),
            html.Div(className="panel viz", children=[
                dcc.Markdown(className="narrative", children=(
                    "**Where do China's zones go — and why?** Filter the catalog at left. The map shades "
                    "each zone by the covariate you choose; the histogram compares that covariate's "
                    "distribution in *your selection* against *all zones nationally*; the timeline shows "
                    "the approval wave. Try selecting only **State Council** zones and watch them pull "
                    "toward the coast — the export-orientation logic of Chinese zone policy.")),
                dcc.Graph(id="t1-map", config={"displayModeBar": False}),
                html.Div(className="viz-row", children=[
                    dcc.Graph(id="t1-dist", config={"displayModeBar": False}, className="half"),
                    dcc.Graph(id="t1-time", config={"displayModeBar": False}, className="half"),
                ]),
            ]),
        ])
    if tab == "eventstudy":
        return render_eventstudy()
    return html.Div(className="grid", children=[
        control_panel_tab2(),
        html.Div(className="panel viz", children=[
            dcc.Markdown(className="narrative", children=(
                "**How do zone-hosting counties differ from the rest?** Set the threshold that defines a "
                "“zone county,” then read the effect chart: each bar is the gap between zone and non-zone "
                "counties on one covariate. With standardized mean difference, dotted lines mark Cohen's "
                "*d* of 0.2 / 0.5 / 0.8 (small / medium / large). **Teal = zone counties higher; "
                "terracotta = zone counties lower.** Watch the distance-to-coast bars stay large and "
                "negative as you raise the threshold — denser zone clusters sit even closer to the coast.")),
            dcc.Graph(id="t2-map", config={"displayModeBar": False}),
            html.Div(className="viz-row", children=[
                dcc.Graph(id="t2-smd", config={"displayModeBar": False}, className="half"),
                dcc.Graph(id="t2-dist", config={"displayModeBar": False}, className="half"),
            ]),
        ]),
    ])


def render_eventstudy():
    return html.Div(className="grid", children=[
        control_panel_tab3(),
        html.Div(className="panel viz", children=[
            dcc.Markdown(className="narrative", children=(
                "**Did the ground move after designation?** This is an event study built on the outcome "
                "the catalog's own time points support exactly — built-up area at 1990 / 2000 / 2010 / "
                "2015 / 2020, aligned to each zone's approval year (τ = 0). The top chart traces built-up "
                "by years-relative-to-designation; built-up climbs through τ = 0, **but it is already "
                "rising before designation** — the signature of selection, not a clean treatment effect. "
                "The selection check below makes the point sharper: treated zones sit far above the "
                "non-zone county baseline *already in 1990*, before most were designated. "
                "*This is descriptive — not an estimated DiD with fixed effects and clustered errors. An "
                "annual-VIIRS county event study would need a per-county designation-year join, and only "
                "~110 counties have a usable post-2013 pre-period, so built-up is the honest outcome to "
                "show interactively here.*")),
            dcc.Graph(id="t3-event", config={"displayModeBar": False}),
            html.Div(className="viz-row", children=[
                dcc.Graph(id="t3-baseline", config={"displayModeBar": False}, className="half"),
                dcc.Graph(id="t3-prepost", config={"displayModeBar": False}, className="half"),
            ]),
        ]),
    ])


@callback(
    Output("t1-map", "figure"), Output("t1-dist", "figure"),
    Output("t1-time", "figure"), Output("t1-readout", "children"),
    Input("t1-province", "value"), Input("t1-type", "value"),
    Input("t1-level", "value"), Input("t1-years", "value"),
    Input("t1-covar", "value"),
)
def update_tab1(provinces, types, level, years, covar):
    dff = filter_zones(provinces, types, level, years)
    label, unit, _ = ZONE_COVARS[covar]
    if len(dff):
        sel_med, nat_med = dff[covar].median(), ZONES[covar].median()
        readout = [html.Span(f"{len(dff):,}", className="big"), html.Span(" zones selected", className="lab"),
                   html.Div(f"Median {label.lower()}: {sel_med:,.0f} {unit}", className="sub"),
                   html.Div(f"National median: {nat_med:,.0f} {unit}", className="sub muted")]
    else:
        readout = [html.Span("0", className="big"), html.Span(" zones match", className="lab")]
    return (fig_zone_map(dff, covar), fig_covariate_distribution(dff, covar),
            fig_approvals_timeline(dff), readout)


@callback(
    Output("t2-map", "figure"), Output("t2-smd", "figure"),
    Output("t2-dist", "figure"), Output("t2-readout", "children"),
    Input("t2-threshold", "value"), Input("t2-stat", "value"),
    Input("t2-covar", "value"), Input("t2-province", "value"),
    Input("t2-log", "value"),
)
def update_tab2(threshold, statistic, covar, provinces, log):
    stats = build_comparison(COUNTIES, threshold, provinces)
    row = stats[stats["column"] == covar].iloc[0]
    smd = row["smd"]
    readout = [
        html.Span(f"{int(row['n_zone']):,}", className="big"), html.Span(" zone counties", className="lab"),
        html.Div(f"vs {int(row['n_nonzone']):,} non-zone (threshold ≥ {threshold})", className="sub"),
        html.Div(f"SMD on {COUNTY_COVARS[covar][0].lower()}: {smd:+.2f} ({effect_label(smd)})",
                 className="sub", style={"color": TEAL if smd >= 0 else TERRA, "fontWeight": 600}),
    ]
    return (fig_county_map(threshold, provinces),
            fig_smd_bars(stats, statistic, covar),
            fig_group_distributions(threshold, provinces, covar, log == "log"),
            readout)


@callback(
    Output("t3-event", "figure"), Output("t3-baseline", "figure"),
    Output("t3-prepost", "figure"), Output("t3-readout", "children"),
    Input("t3-cohorts", "value"), Input("t3-type", "value"),
    Input("t3-level", "value"), Input("t3-norm", "value"),
    Input("t3-extras", "value"),
)
def update_tab3(cohorts, types, level, norm, extras):
    extras = extras or []
    dff = _zone_subset(cohorts, types, level)
    if len(dff):
        pre_m, post_m = dff["built_pre"].median(), dff["built_post"].median()
        fold = post_m / pre_m if pre_m else float("nan")
        base_fold = NONZONE_BASELINE[2020] / NONZONE_BASELINE[1990]
        readout = [
            html.Span(f"{len(dff):,}", className="big"), html.Span(" zones in view", className="lab"),
            html.Div(f"Median built-up {pre_m:,.0f} → {post_m:,.0f} m²  ({fold:.2f}× pre→post)",
                     className="sub"),
            html.Div(f"Non-zone county baseline grew {base_fold:.2f}× over 1990–2020 — the secular trend "
                     "designation cannot be separated from.", className="sub muted"),
        ]
    else:
        readout = [html.Span("0", className="big"), html.Span(" zones match", className="lab")]
    return (fig_event_study(dff, cohorts, norm),
            fig_treated_vs_baseline(dff, "baseline" in extras),
            fig_prepost_scatter(dff, "logscatter" in extras),
            readout)


if __name__ == "__main__":
    app.run(debug=True, port=8050)
