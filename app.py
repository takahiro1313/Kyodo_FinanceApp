# app.py — 財務ダッシュボード（PL/BS/CF：3年・百万円）

import streamlit as st
import pandas as pd
import altair as alt
import re
from datetime import datetime, date
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import numpy as np

# ------------ 環境変数読み込み（.env） ------------
load_dotenv()
client = OpenAI()

# ------------ Streamlit 画面設定 ------------
st.set_page_config(page_title="財務ダッシュボード", layout="wide", page_icon="📊")
st.title("財務ダッシュボード（PL / BS / CF）")

# ------------ ファイル入力 ------------
FILE_DEFAULT = "financial_demo_v6.xlsx"

uploaded = st.file_uploader("データを選択", type=["xlsx"])
file = uploaded if uploaded else (Path(FILE_DEFAULT) if Path(FILE_DEFAULT).exists() else None)

if not file:
    st.info(f"`{FILE_DEFAULT}` を同じフォルダに置くか、ここにアップロードしてください。")
    st.stop()

# ------------ Excel 読み込み ------------
try:
    PL = pd.read_excel(file, sheet_name="PL")
    BS = pd.read_excel(file, sheet_name="BS")
    CF = pd.read_excel(file, sheet_name="CF")
except Exception as e:
    st.error(f"Excelの読み込みに失敗しました: {e}")
    st.stop()


# ------------ 年度列の抽出 ------------
def get_year_cols(df: pd.DataFrame):
    cols = df.columns.tolist()
    if len(cols) < 4 or cols[0] != "科目":
        raise ValueError("シートの先頭列が『科目』、以降に年度列（3列）がある形式にしてください。")
    return cols[1], cols[2], cols[3]


def extract_year(lbl):
    if isinstance(lbl, (pd.Timestamp, datetime, date)):
        return int(pd.to_datetime(lbl).year)
    s = str(lbl)
    m = re.findall(r"(\d{4})", s)
    return int(m[-1]) if m else s


Y23, Y24, Y25 = get_year_cols(PL)
YEARS = [extract_year(s) for s in (Y23, Y24, Y25)]

# ------------ Altair テーマ & 定数 ------------
BAR_SIZE = 28
LINE_WIDTH = 3
POINT_SIZE = 80

COLOR_BAR_PRIMARY = "#9ecae1"
COLOR_CF_SALES = "#4C78A8"
COLOR_CF_INVEST = "#F58518"
COLOR_CF_FIN = "#54A24B"
COLOR_ASSET_BAR = "#bcbddc"
COLOR_EQUITY_LINE = "#de2d26"

COLOR_RATE_OP = "#F58518"   # 営業利益率
COLOR_RATE_OCF = "#E45756"  # 営業CFマージン

alt.themes.register(
    "clean",
    lambda: {
        "config": {
            "view": {"strokeWidth": 0},
            "axis": {
                "labelFontSize": 12,
                "titleFontSize": 12,
                "grid": True,
                "gridColor": "#eaeaea",
            },
            "legend": {"orient": "top", "labelFontSize": 11, "titleFontSize": 11},
        }
    },
)
alt.themes.enable("clean")


# ------------ 共通ユーティリティ ------------
def get_val(df, account, col):
    row = df.loc[df["科目"] == account]
    if row.empty:
        return None
    v = row.iloc[0][col]
    try:
        return float(v)
    except Exception:
        return None


def melt_long(df):
    long = df.melt(id_vars="科目", var_name="年度", value_name="金額").dropna(subset=["金額"])
    long["年度"] = long["年度"].apply(extract_year)
    return long


def ratio(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b

def safe_pct_series(num: pd.Series, denom: pd.Series) -> pd.Series:
    """0割りやNaNを避けて%を計算（∞を出さない）"""
    num = num.astype(float)
    denom = denom.astype(float)
    mask = (denom != 0) & denom.notna() & num.notna()
    result = pd.Series(np.nan, index=num.index, dtype="float")
    result[mask] = num[mask] / denom[mask] * 100
    return result

def pct(a):
    return None if a is None else 100 * a


def fmt_money(x):
    return "—" if x is None else f"{x:,.0f}"


def fmt_pct(x):
    return "—" if x is None else f"{x:.1f}%"


PL_long, BS_long, CF_long = melt_long(PL), melt_long(BS), melt_long(CF)

# ------------ AI コメント共通関数 ------------
@st.cache_data(show_spinner=False)
def generate_chart_comment(title: str, description: str, table_markdown: str) -> str:
    """
    各グラフの直下に表示する短いコメントを生成。
    """
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは日本の経営者向けに財務データをわかりやすく説明するアナリストです。"
                "グラフの内容を1〜3行で要約し、『今何が起きているか』『どこに着目すべきか』を示してください。"
                "難しい専門用語は避け、社長が直感的に理解できる日本語で説明してください。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"グラフタイトル: {title}\n"
                f"このグラフで見たいポイント: {description}\n\n"
                f"データサマリー（Markdownテーブル）:\n{table_markdown}\n\n"
                "箇条書き2〜3個か、短い説明文1つで答えてください。"
            ),
        },
    ]
    try:
        res = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            temperature=0.4,
        )
        return res.choices[0].message.content.strip()
    except Exception:
        # APIエラー時は何も表示しない
        return ""


# ------------ KPI算出 ------------
latest_col, prev_col = Y25, Y24

sales_now = get_val(PL, "売上高", latest_col)
op_now = get_val(PL, "営業利益", latest_col)
net_now = get_val(PL, "当期純利益", latest_col)

sales_prev = get_val(PL, "売上高", prev_col)
op_prev = get_val(PL, "営業利益", prev_col)
net_prev = get_val(PL, "当期純利益", prev_col)

opm_now = ratio(op_now, sales_now)
opm_prev = ratio(op_prev, sales_prev)

assets_now = get_val(BS, "資産合計", latest_col)
equity_now = get_val(BS, "純資産合計", latest_col)
assets_prev = get_val(BS, "資産合計", prev_col)
equity_prev = get_val(BS, "純資産合計", prev_col)

equity_ratio_now = ratio(equity_now, assets_now)
equity_ratio_prev = ratio(equity_prev, assets_prev)

# 営業CF（詳細CFでも合計行の科目名はこれでOK）
ocf_now = get_val(CF, "営業活動によるキャッシュ・フロー", latest_col)
ocf_prev = get_val(CF, "営業活動によるキャッシュ・フロー", prev_col)

ocf_margin_now = ratio(ocf_now, sales_now)
ocf_margin_prev = ratio(ocf_prev, sales_prev)

roe_now = ratio(
    net_now,
    (equity_now + equity_prev) / 2
    if (equity_now is not None and equity_prev is not None)
    else None,
)

# ------------------ AI用コンテキスト生成 ------------------
def build_financial_context() -> str:
    """PL / BS / CF と主要KPIをまとめてテキスト化（AIに渡す用）"""

    # 3表を Markdown 形式に（tabulate が必要）
    pl_md = PL.to_markdown(index=False)
    bs_md = BS.to_markdown(index=False)
    cf_md = CF.to_markdown(index=False)

    kpi_text = f"""
【主要KPI（最新年度 {YEARS[-1]}）】
- 売上高：{fmt_money(sales_now)} 百万円
- 営業利益：{fmt_money(op_now)} 百万円（営業利益率：{fmt_pct(pct(opm_now))}）
- 当期純利益：{fmt_money(net_now)} 百万円
- 営業CF：{fmt_money(ocf_now)} 百万円（営業CFマージン：{fmt_pct(pct(ocf_margin_now))}）
- フリーCF：{fmt_money(fcf_now)} 百万円（FCFマージン：{fmt_pct(pct(fcf_margin_now))}）
- 総資産：{fmt_money(assets_now)} 百万円
- 純資産：{fmt_money(equity_now)} 百万円（自己資本比率：{fmt_pct(pct(equity_ratio_now))}）
"""

    ctx = f"""
あなたは日本企業の社長向けの財務アドバイザーです。
以下の PL / BS / CF（いずれも百万円単位）と主要KPIを前提に、
経営者の質問に日本語でわかりやすく答えてください。

### 主要KPI
{kpi_text}

### PL（損益計算書）
{pl_md}

### BS（貸借対照表）
{bs_md}

### CF（キャッシュ・フロー計算書）
{cf_md}
"""
    return ctx


SYSTEM_PROMPT_QA = """
あなたは日本企業の社長をサポートするCFO兼コンサルタントです。

- 回答は必ず日本語で、専門用語はかみ砕いて説明してください。
- まず「結論」を1〜2文で述べ、その後に根拠や補足を簡潔に書きます。
- 数字や推移を説明するときは、「売上は◯◯年から◯◯年にかけて△△%増加」など、
  トレンドが直感的にわかる表現を心がけてください。
- 与えられた財務データから推測できないことは、
  「このデータだけでは断定できませんが、一般的には〜」のように回答してください。
"""


# ---- CF詳細版用 CapEx / FCF ----
def to_num(x):
    """'△' やカンマが混ざっていても数値化（保険的実装）"""
    if pd.isna(x):
        return None
    s = str(x).replace(",", "").replace("△", "-").strip()
    try:
        return float(s)
    except Exception:
        return None


def get_num(df, account, col):
    row = df.loc[df["科目"].astype(str) == account]
    if row.empty:
        return None
    return to_num(row.iloc[0][col])


def capex_amount(df, col):
    """
    詳細CFシート前提の設備投資額（CapEx）の算出。

    - 有形固定資産の取得による支出
    - 無形固定資産の取得による支出

    CFでは支出はマイナスで記載されている前提。
    """
    capex_rows = [
        "有形固定資産の取得による支出",
        "無形固定資産の取得による支出",
    ]
    vals = []
    for name in capex_rows:
        v = get_num(df, name, col)
        if v is not None:
            vals.append(v)

    if not vals:
        return None

    # 支出（マイナス）→ 設備投資額（プラス）として扱う
    return sum(-v for v in vals)


capex_now = capex_amount(CF, latest_col)
capex_prev = capex_amount(CF, prev_col)

fcf_now = (ocf_now - capex_now) if (ocf_now is not None and capex_now is not None) else None
fcf_prev = (ocf_prev - capex_prev) if (ocf_prev is not None and capex_prev is not None) else None

fcf_margin_now = ratio(fcf_now, sales_now)
fcf_margin_prev = ratio(fcf_prev, sales_prev)

# ------------ KPIカード ------------
st.subheader("ハイライト（最新年度）")

use_fcf = st.toggle("資金力指標を FCF ベースに切り替える", value=False)

c1, c2, c3, c4 = st.columns(4)

# 売上高
c1.metric(
    "売上高（百万円）",
    fmt_money(sales_now),
    f"{fmt_money((sales_now or 0) - (sales_prev or 0))} vs 前年",
)
c1.caption("会社の規模")

# 営業利益率
c2.metric(
    "営業利益率",
    fmt_pct(pct(opm_now)),
    f"{fmt_pct(pct((opm_now or 0) - (opm_prev or 0)))} vs 前年",
)
c2.caption("収益性")

# 営業CF / FCF マージン
if use_fcf:
    c3.metric(
        "フリーCFマージン",
        fmt_pct(pct(fcf_margin_now)),
        f"{fmt_pct(pct((fcf_margin_now or 0) - (fcf_margin_prev or 0)))} vs 前年",
    )
    c3.caption("資金力（投資後の自由現金）")
else:
    c3.metric(
        "営業CFマージン",
        fmt_pct(pct(ocf_margin_now)),
        f"{fmt_pct(pct((ocf_margin_now or 0) - (ocf_margin_prev or 0)))} vs 前年",
    )
    c3.caption("資金力（営業で稼ぐ現金力）")

# 自己資本比率
c4.metric(
    "自己資本比率",
    fmt_pct(pct(equity_ratio_now)),
    f"{fmt_pct(pct((equity_ratio_now or 0) - (equity_ratio_prev or 0)))} vs 前年",
)
c4.caption("安定性")

st.divider()

# ================== グラフ① 売上 × 営業利益率・営業CFマージン ==================
st.subheader("売上高 × 営業利益率・営業CFマージン（全体俯瞰）")

sales_df = (
    PL_long[PL_long["科目"] == "売上高"][["年度", "金額"]]
    .rename(columns={"金額": "売上高"})
    .sort_values("年度")
)

op_df = (
    PL_long[PL_long["科目"] == "営業利益"][["年度", "金額"]]
    .merge(sales_df, on="年度")
)
# 安全な%計算（売上ゼロは NaN）
op_df["営業利益率"] = safe_pct_series(op_df["金額"], op_df["売上高"])
op_df = op_df[["年度", "営業利益率"]]

ocf_df = (
    CF_long[CF_long["科目"] == "営業活動によるキャッシュ・フロー"][["年度", "金額"]]
    .merge(sales_df, on="年度")
)
ocf_df["営業CFマージン"] = safe_pct_series(ocf_df["金額"], ocf_df["売上高"])
ocf_df = ocf_df[["年度", "営業CFマージン"]]

rates = op_df.merge(ocf_df, on="年度", how="inner").sort_values("年度")

# 長い形に変換 → ∞ を NaN にしてから NaN 行を落とす
rates_long = rates.melt(id_vars="年度", var_name="指標", value_name="割合")
rates_long["割合"] = rates_long["割合"].replace([np.inf, -np.inf], np.nan)
rates_long = rates_long.dropna(subset=["割合"])


base = alt.Chart(sales_df).encode(
    x=alt.X("年度:O", axis=alt.Axis(labelAngle=0))
)

bar = base.mark_bar(size=BAR_SIZE, color=COLOR_BAR_PRIMARY).encode(
    y=alt.Y(
        "売上高:Q",
        axis=alt.Axis(
            title="売上高（百万円）",
            format=",",
            formatType="number",
            labelExpr="format(datum.value, ',')",
        ),
    ),
    tooltip=[alt.Tooltip("年度:O"), alt.Tooltip("売上高:Q", format=",.0f")],
)

rate_colors = alt.Scale(
    domain=["営業利益率", "営業CFマージン"],
    range=[COLOR_RATE_OP, COLOR_RATE_OCF],
)

lines = (
    alt.Chart(rates_long)
    .mark_line(point=alt.OverlayMarkDef(size=POINT_SIZE), strokeWidth=LINE_WIDTH)
    .encode(
        x="年度:O",
        y=alt.Y(
            "割合:Q",
            axis=alt.Axis(title="利益率（%）", orient="right", format=".1f"),
            scale=alt.Scale(zero=False),
        ),
        color=alt.Color("指標:N", scale=rate_colors, title=None),
        strokeDash=alt.StrokeDash(
            "指標:N",
            scale=alt.Scale(
                domain=["営業利益率", "営業CFマージン"],
                range=[[0, 0], [4, 3]],
            ),
        ),
        tooltip=[
            alt.Tooltip("年度:O"),
            alt.Tooltip("指標:N"),
            alt.Tooltip("割合:Q", format=".1f"),
        ],
    )
)

chart1 = alt.layer(bar, lines).resolve_scale(y="independent").properties(height=360)
st.altair_chart(chart1, use_container_width=True)

# ---- AI コメント（グラフ①） ----
rates_for_ai = rates.copy()
rates_for_ai["営業利益率(%)"] = rates_for_ai["営業利益率"].round(1)
rates_for_ai["営業CFマージン(%)"] = rates_for_ai["営業CFマージン"].round(1)
rates_for_ai = rates_for_ai[["年度", "営業利益率(%)", "営業CFマージン(%)"]]
table_md_1 = rates_for_ai.to_markdown(index=False)

ai_comment_1 = generate_chart_comment(
    title="売上高 × 営業利益率・営業CFマージン",
    description="売上の伸びに対して、営業利益率と営業CFマージンがどのように推移しているかを把握したい。",
    table_markdown=table_md_1,
)
if ai_comment_1:
    st.markdown("**AIによるグラフ解説**")
    st.markdown(ai_comment_1)

st.divider()

# ================== グラフ④ 営業利益 & 当期純利益の推移 ==================
st.subheader("営業利益・当期純利益の推移（百万円）")

profit_long = PL_long[PL_long["科目"].isin(["営業利益", "当期純利益"])].copy()
profit_long = profit_long.sort_values(["科目", "年度"])

# 科目ごとに YoY 計算
profit_long["YoY"] = (
    profit_long.groupby("科目")["金額"].pct_change() * 100
)

profit_long["YoY"] = profit_long["YoY"].replace([np.inf, -np.inf], np.nan)

profit_chart = (
    alt.Chart(profit_long)
    .mark_bar(size=BAR_SIZE)
    .encode(
        x=alt.X("年度:O", axis=alt.Axis(labelAngle=0)),
        y=alt.Y(
            "金額:Q",
            axis=alt.Axis(
                title="金額（百万円）",
                format=",",
                formatType="number",
                labelExpr="format(datum.value, ',')",
            ),
        ),
        color=alt.Color("科目:N", title=None),
        tooltip=[
            alt.Tooltip("科目:N"),
            alt.Tooltip("年度:O"),
            alt.Tooltip("金額:Q", format=",.0f"),
            alt.Tooltip("YoY:Q", format=".1f", title="前年比（%）"),
        ],
    )
)

# 棒の上に前年比ラベル（前年比が存在する年だけ）
label_chart = (
    alt.Chart(profit_long.dropna(subset=["YoY"]))
    .mark_text(dy=-8, size=11)
    .encode(
        x="年度:O",
        y="金額:Q",
        color=alt.Color("科目:N", legend=None),
        text=alt.Text("YoY:Q", format=".1f"),
    )
)

st.altair_chart(
    (profit_chart + label_chart).properties(height=320),
    use_container_width=True,
)

# ---- AI コメント（グラフ④） ----
profit_for_ai = (
    profit_long.pivot_table(
        index="年度", columns="科目", values="金額", aggfunc="first"
    )
    .round(0)
    .sort_index()
)
table_md_4 = profit_for_ai.to_markdown()

ai_comment_4 = generate_chart_comment(
    title="営業利益・当期純利益の推移（百万円）",
    description="営業利益と最終利益がどれくらい伸びているか、またどの年度で大きな変化があったかを把握したい。",
    table_markdown=table_md_4,
)
if ai_comment_4:
    st.markdown("**AIによるグラフ解説**")
    st.markdown(ai_comment_4)

st.divider()

# ================== グラフ② キャッシュ・フロー構造 ==================
st.subheader("キャッシュ・フローの構造（百万円）")

cf_pivot = CF_long.pivot_table(
    index="年度", columns="科目", values="金額", aggfunc="first"
)

cfplot = (
    cf_pivot[
        [
            "営業活動によるキャッシュ・フロー",
            "投資活動によるキャッシュ・フロー",
            "財務活動によるキャッシュ・フロー",
        ]
    ]
    .reset_index()
    .melt("年度", var_name="区分", value_name="金額")
)

color_scale_cf = alt.Scale(
    domain=list(cfplot["区分"].unique()),
    range=[COLOR_CF_SALES, COLOR_CF_INVEST, COLOR_CF_FIN],
)

zero_rule = (
    alt.Chart(pd.DataFrame({"y": [0]}))
    .mark_rule(color="#999", strokeDash=[4, 4])
    .encode(y="y:Q")
)

cf_chart = (
    alt.Chart(cfplot)
    .mark_bar(size=BAR_SIZE)
    .encode(
        x=alt.X("年度:O", axis=alt.Axis(labelAngle=0)),
        y=alt.Y(
            "金額:Q",
            axis=alt.Axis(
                title="金額（百万円）",
                format=",",
                formatType="number",
                labelExpr="format(datum.value, ',')",
            ),
        ),
        color=alt.Color("区分:N", scale=color_scale_cf, title=None),
        tooltip=[
            alt.Tooltip("年度:O"),
            alt.Tooltip("区分:N"),
            alt.Tooltip("金額:Q", format=",.0f"),
        ],
    )
)

st.altair_chart(zero_rule + cf_chart.properties(height=320), use_container_width=True)

# ---- AI コメント（グラフ②） ----
cf_for_ai = (
    cfplot.pivot(index="年度", columns="区分", values="金額")
    .round(0)
    .sort_index()
)
table_md_2 = cf_for_ai.to_markdown()

ai_comment_2 = generate_chart_comment(
    title="キャッシュ・フローの構造（百万円）",
    description="営業・投資・財務それぞれのキャッシュフローのバランスと、直近年度での特徴を知りたい。",
    table_markdown=table_md_2,
)
if ai_comment_2:
    st.markdown("**AIによるグラフ解説**")
    st.markdown(ai_comment_2)

st.divider()

# ================== グラフ③ 財務体質 ==================
st.subheader("財務体質：総資産 × 自己資本比率（%）")

assets = BS_long[BS_long["科目"] == "資産合計"].rename(columns={"金額": "資産合計"})
equity = BS_long[BS_long["科目"] == "純資産合計"].rename(columns={"金額": "純資産合計"})

bs_m = pd.merge(
    assets[["年度", "資産合計"]],
    equity[["年度", "純資産合計"]],
    on="年度",
    how="inner",
).sort_values("年度")

bs_m["自己資本比率"] = safe_pct_series(bs_m["純資産合計"], bs_m["資産合計"])


bar2 = (
    alt.Chart(bs_m)
    .mark_bar(size=BAR_SIZE, color=COLOR_ASSET_BAR)
    .encode(
        x=alt.X("年度:O", axis=alt.Axis(labelAngle=0)),
        y=alt.Y(
            "資産合計:Q",
            axis=alt.Axis(
                title="総資産（百万円）",
                format=",",
                formatType="number",
                labelExpr="format(datum.value, ',')",
            ),
        ),
        tooltip=[
            alt.Tooltip("年度:O"),
            alt.Tooltip("資産合計:Q", format=",.0f"),
            alt.Tooltip("純資産合計:Q", format=",.0f"),
            alt.Tooltip("自己資本比率:Q", format=".1f"),
        ],
    )
)

line2 = (
    alt.Chart(bs_m)
    .mark_line(
        point=alt.OverlayMarkDef(size=POINT_SIZE),
        strokeWidth=LINE_WIDTH,
        color=COLOR_EQUITY_LINE,
    )
    .encode(
        x="年度:O",
        y=alt.Y(
            "自己資本比率:Q",
            axis=alt.Axis(title="自己資本比率（%）", format=".1f"),
            scale=alt.Scale(zero=False),
        ),
    )
)

st.altair_chart(
    alt.layer(bar2, line2).resolve_scale(y="independent").properties(height=320),
    use_container_width=True,
)

# ---- AI コメント（グラフ③） ----
bs_for_ai = bs_m.copy()
bs_for_ai["資産合計"] = bs_for_ai["資産合計"].round(0)
bs_for_ai["純資産合計"] = bs_for_ai["純資産合計"].round(0)
bs_for_ai["自己資本比率(%)"] = bs_for_ai["自己資本比率"].round(1)
bs_for_ai = bs_for_ai[["年度", "資産合計", "純資産合計", "自己資本比率(%)"]]
table_md_3 = bs_for_ai.to_markdown(index=False)

ai_comment_3 = generate_chart_comment(
    title="財務体質：総資産 × 自己資本比率（%）",
    description="総資産の成長と自己資本比率の推移から、財務の安定性やレバレッジの変化を知りたい。",
    table_markdown=table_md_3,
)
if ai_comment_3:
    st.markdown("**AIによるグラフ解説**")
    st.markdown(ai_comment_3)

st.divider()

# ------------------ AIによる財務Q&A（経営者向け） ------------------
st.subheader("AIによる財務Q&A（経営者向け）")

st.caption("例：『営業CFが低下した理由は？』『自己資本比率はどの程度あれば安心ですか？』など")

# チャット履歴を session_state に保持
if "qa_messages" not in st.session_state:
    st.session_state.qa_messages = []

# これまでのやり取りを表示
for msg in st.session_state.qa_messages:
    role = "user" if msg["role"] == "user" else "assistant"
    with st.chat_message(role):
        st.markdown(msg["content"])

# ユーザー入力欄（画面下部に固定されるチャット入力）
user_q = st.chat_input("経営について気になる点を聞いてみてください")

if user_q:
    # ユーザー発話を表示＆履歴に追加
    st.session_state.qa_messages.append({"role": "user", "content": user_q})
    with st.chat_message("user"):
        st.markdown(user_q)

    # AIからの回答
    with st.chat_message("assistant"):
        with st.spinner("AIが財務データをもとに考えています..."):
            try:
                context_text = build_financial_context()

                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT_QA},
                    {"role": "system", "content": context_text},
                ]

                # 直近のやりとりも少しだけ付ける（長くなりすぎないように後ろから数件）
                recent = st.session_state.qa_messages[-6:]
                messages.extend(recent)

                resp = client.chat.completions.create(
                    model="gpt-4o-mini",  # すでに使っているモデルに合わせてOK
                    messages=messages,
                    temperature=0.4,
                )
                answer = resp.choices[0].message.content
            except Exception as e:
                answer = f"AIコメントの生成中にエラーが発生しました: {e}"

            st.markdown(answer)
            st.session_state.qa_messages.append({"role": "assistant", "content": answer})

