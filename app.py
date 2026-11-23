import io
import re
import pandas as pd
import streamlit as st
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

st.set_page_config(
    page_title="萌面打劫 | 部落战出勤与漏刀监控",
    page_icon="⚔️",
    layout="wide",
)

DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1GYL8qHNSyG8rGXycw_mbYIy-BuCpxlYPfYH7aYTvwPg/edit?gid=0#gid=0"


def convert_gsheet_to_csv_url(url: str) -> str:
    """将 Google Sheets 分享链接自动转换为 CSV 导出链接"""
    url = url.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return url
    sheet_id = match.group(1)
    gid_match = re.search(r"[?&#]gid=([0-9]+)", url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


@st.cache_data(ttl=120)
def load_from_gsheet(url: str) -> pd.DataFrame:
    csv_url = convert_gsheet_to_csv_url(url)
    return pd.read_csv(csv_url)


def process_war_data(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = raw_df.copy()
    required_cols = [
        "Name", "Tag", "Town Hall", "Wars Participated", "Number of Attacks",
        "Total Stars", "Avg. Stars", "True Stars", "Avg. True Stars",
        "Total Dest", "Avg. Dest", "Three Stars", "Two Stars", "One Stars",
        "Zero Stars", "Missed"
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"表格缺少必要列：{', '.join(missing)}，请确认这是 ClashPerk 导出的 War Stats 表格。")

    df = df.dropna(subset=["Name"]).copy()

    num_cols = [
        "Town Hall", "Wars Participated", "Number of Attacks",
        "Total Stars", "Avg. Stars", "True Stars", "Avg. True Stars",
        "Total Dest", "Avg. Dest", "Three Stars", "Two Stars", "One Stars",
        "Zero Stars", "Missed"
    ]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    int_cols = [
        "Town Hall", "Wars Participated", "Number of Attacks",
        "Total Stars", "True Stars", "Three Stars", "Two Stars",
        "One Stars", "Zero Stars", "Missed"
    ]
    for col in int_cols:
        df[col] = df[col].astype(int)

    df["应出刀数"] = df["Wars Participated"] * 2
    df["漏刀率(%)"] = df.apply(
        lambda r: round(r["Missed"] / r["应出刀数"] * 100, 1) if r["应出刀数"] > 0 else 0.0,
        axis=1,
    )
    df["三星率(%)"] = df.apply(
        lambda r: round(r["Three Stars"] / r["Number of Attacks"] * 100, 1)
        if r["Number of Attacks"] > 0
        else 0.0,
        axis=1,
    )

    def classify_status(row):
        if row["Missed"] >= 6 or (row["Missed"] > 0 and row["Number of Attacks"] == 0):
            return "🔴 严重漏打"
        elif row["Missed"] > 0:
            return "🟡 一般漏打"
        return "🟢 全勤"

    df["出勤状态"] = df.apply(classify_status, axis=1)

    df = df.sort_values(
        by=["Missed", "漏刀率(%)", "Wars Participated", "Total Stars", "Name"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)

    return df


def build_styled_excel(df: pd.DataFrame) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "出勤与漏刀统计"

    navy_fill = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
    severe_fill = PatternFill(start_color="FADBD8", end_color="FADBD8", fill_type="solid")
    minor_fill = PatternFill(start_color="FCF3CF", end_color="FCF3CF", fill_type="solid")
    ok_fill = PatternFill(start_color="E8F8F5", end_color="E8F8F5", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    font_header = Font(name="Microsoft YaHei", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Microsoft YaHei", size=10, color="1E293B")
    font_severe = Font(name="Microsoft YaHei", size=10, bold=True, color="922B21")
    font_minor = Font(name="Microsoft YaHei", size=10, bold=True, color="7D6608")
    font_ok = Font(name="Microsoft YaHei", size=10, bold=True, color="117864")

    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    export_cols = [
        ("出勤状态", "出勤状态"),
        ("Name", "成员名称"),
        ("Tag", "玩家标签"),
        ("Town Hall", "大本营"),
        ("Wars Participated", "参战场次"),
        ("应出刀数", "应出刀数"),
        ("Number of Attacks", "实际出刀"),
        ("Missed", "漏打刀数"),
        ("漏刀率(%)", "漏刀率(%)"),
        ("Total Stars", "总得星"),
        ("Avg. Stars", "刀均得星"),
        ("True Stars", "真实新星"),
        ("Avg. True Stars", "刀均新星"),
        ("Three Stars", "三星数"),
        ("三星率(%)", "三星率(%)"),
    ]

    for c_idx, (_, title) in enumerate(export_cols, start=1):
        cell = ws.cell(row=1, column=c_idx, value=title)
        cell.fill = navy_fill
        cell.font = font_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[1].height = 26

    for r_idx, row in df.iterrows():
        excel_r = r_idx + 2
        missed = row["Missed"]
        attacks = row["Number of Attacks"]
        is_severe = missed >= 6 or (missed > 0 and attacks == 0)
        is_minor = missed > 0 and not is_severe

        row_fill = severe_fill if is_severe else (minor_fill if is_minor else (zebra_fill if r_idx % 2 == 1 else white_fill))
        row_font = font_severe if is_severe else (font_minor if is_minor else font_data)

        for c_idx, (col_key, _) in enumerate(export_cols, start=1):
            val = row[col_key]
            cell = ws.cell(row=excel_r, column=c_idx, value=val)
            cell.fill = row_fill
            cell.font = row_font
            cell.border = border
            cell.alignment = Alignment(horizontal="left" if col_key == "Name" else "center", vertical="center")
            if col_key == "出勤状态" and missed == 0:
                cell.fill = ok_fill
                cell.font = font_ok
        ws.row_dimensions[excel_r].height = 21

    for c_idx in range(1, len(export_cols) + 1):
        ws.column_dimensions[get_column_letter(c_idx)].width = 14
    ws.column_dimensions["B"].width = 18
    ws.freeze_panes = "C2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


st.title("⚔️ 萌面打劫 — 部落战出勤与漏刀看板")
st.caption("直连 ClashPerk 导出的 Google Sheets，自动分级高亮漏打成员并生成群通知")

with st.sidebar:
    st.header("📥 数据源设置")
    source_mode = st.radio("选择导入方式", ["粘贴 Google Sheet 链接", "上传本地 Excel / CSV"])

    raw_df = None
    if source_mode == "粘贴 Google Sheet 链接":
        sheet_url = st.text_input(
            "ClashPerk Google Sheet 链接",
            value=DEFAULT_SHEET_URL,
            help="在 Discord 使用 /export wars 后，复制 Google Sheet 按钮链接粘贴到此处",
        )
        if st.button("🔄 立即刷新数据", use_container_width=True):
            st.cache_data.clear()
        if sheet_url:
            try:
                raw_df = load_from_gsheet(sheet_url)
            except Exception as e:
                st.error(f"读取 Google Sheet 失败，请确认链接已开启查看权限。错误详情：{e}")
    else:
        uploaded = st.file_uploader("上传 War Stats 文件 (.xlsx / .csv)", type=["xlsx", "csv"])
        if uploaded is not None:
            if uploaded.name.endswith(".csv"):
                raw_df = pd.read_csv(uploaded)
            else:
                raw_df = pd.read_excel(uploaded)

    st.divider()
    st.header("🔍 筛选条件")
    only_missed = st.checkbox("仅显示有漏打的成员", value=False)
    min_wars = st.slider("最低参战场次", min_value=1, max_value=15, value=1)
    min_missed = st.slider("最低漏打刀数", min_value=0, max_value=15, value=0)

if raw_df is None:
    st.info("请在左侧输入有效的 Google Sheet 链接或上传文件。")
    st.stop()

try:
    df = process_war_data(raw_df)
except Exception as e:
    st.error(str(e))
    st.stop()

total_members = len(df)
full_cnt = int((df["Missed"] == 0).sum())
missed_cnt = int((df["Missed"] > 0).sum())
severe_cnt = int(df["出勤状态"].str.contains("严重").sum())
total_expected = int(df["应出刀数"].sum())
total_missed = int(df["Missed"].sum())
clan_miss_rate = round(total_missed / total_expected * 100, 1) if total_expected > 0 else 0.0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("参战总人数", f"{total_members} 人")
c2.metric("全勤人数 (0漏打)", f"{full_cnt} 人")
c3.metric("漏打人数", f"{missed_cnt} 人", delta=f"严重 {severe_cnt} 人", delta_color="inverse")
c4.metric("累计漏打刀数", f"{total_missed} / {total_expected} 刀")
c5.metric("部落整体漏刀率", f"{clan_miss_rate}%")

st.divider()

filtered_df = df[df["Wars Participated"] >= min_wars].copy()
if only_missed:
    filtered_df = filtered_df[filtered_df["Missed"] > 0]
if min_missed > 0:
    filtered_df = filtered_df[filtered_df["Missed"] >= min_missed]

display_cols = [
    "出勤状态", "Name", "Tag", "Town Hall", "Wars Participated",
    "应出刀数", "Number of Attacks", "Missed", "漏刀率(%)",
    "Total Stars", "Avg. Stars", "Avg. True Stars", "三星率(%)"
]
rename_map = {
    "Name": "成员名称",
    "Tag": "玩家标签",
    "Town Hall": "大本营",
    "Wars Participated": "参战场次",
    "Number of Attacks": "实际出刀",
    "Missed": "漏打刀数",
    "Total Stars": "总得星",
    "Avg. Stars": "刀均得星",
    "Avg. True Stars": "刀均新星",
}

show_df = filtered_df[display_cols].rename(columns=rename_map)


def highlight_rows(row):
    status = str(row["出勤状态"])
    if "严重" in status:
        return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(row)
    elif "一般" in status:
        return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(row)
    return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(row) - 1)


st.subheader(f"📋 成员出勤明细表（当前显示 {len(show_df)} 人）")
st.dataframe(
    show_df.style.apply(highlight_rows, axis=1).format({
        "漏刀率(%)": "{:.1f}%",
        "三星率(%)": "{:.1f}%",
        "刀均得星": "{:.2f}",
        "刀均新星": "{:.2f}",
    }),
    use_container_width=True,
    height=560,
    hide_index=True,
)

col_left, col_right = st.columns([1, 1.4])

with col_left:
    st.subheader("📥 导出高亮版 Excel")
    st.write("下载已自动置顶并红黄高亮标注的完整 `.xlsx` 表格，方便存档或发群。")
    excel_bytes = build_styled_excel(filtered_df)
    st.download_button(
        label="⬇️ 下载高亮统计表 (.xlsx)",
        data=excel_bytes,
        file_name="萌面打劫_部落战出勤统计.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

with col_right:
    st.subheader("📢 一键复制群通知文案")
    severe_list = df[df["出勤状态"].str.contains("严重")]
    minor_list = df[df["出勤状态"].str.contains("一般")]

    lines = [
        "【萌面打劫 部落战出勤通报】",
        f"统计范围：近 {df['Wars Participated'].max()} 场常规战 | 全勤 {full_cnt} 人 | 漏打 {missed_cnt} 人（累计漏 {total_missed} 刀）",
        "",
        "🔴 严重漏打 / 全鸽名单（请自觉调整红牌或说明情况）：",
    ]
    for _, r in severe_list.iterrows():
        lines.append(f"- {r['Name']}：漏 {r['Missed']} 刀（出刀 {r['Number of Attacks']}/{r['应出刀数']}，漏刀率 {r['漏刀率(%)']}%）")

    lines.append("")
    lines.append("🟡 一般漏打提醒（注意战前定好闹钟）：")
    for _, r in minor_list.iterrows():
        lines.append(f"- {r['Name']}：漏 {r['Missed']} 刀（出刀 {r['Number of Attacks']}/{r['应出刀数']}）")

    notice_text = "\n".join(lines)
    st.code(notice_text, language="text")
