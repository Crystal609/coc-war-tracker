import io
import os
import re
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

st.set_page_config(
    page_title="萌面打劫 | 部落战监控",
    page_icon="⚔️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CLAN_TAG = "#2YR9JVCG8"
API_BASE = "https://cocproxy.royaleapi.dev/v1"
HISTORY_FILE = "war_history.csv"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1GYL8qHNSyG8rGXycw_mbYIy-BuCpxlYPfYH7aYTvwPg/edit?gid=0#gid=0"

# 手机端响应式自适应 CSS 优化
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.85rem !important;
        padding-right: 0.85rem !important;
        max-width: 820px;
    }
    .clan-header {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: #ffffff;
        padding: 14px 16px;
        border-radius: 12px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
    }
    .clan-title {
        font-size: 1.22rem;
        font-weight: 700;
        line-height: 1.35;
        margin: 0;
        word-break: break-word;
    }
    .clan-sub {
        font-size: 0.8rem;
        color: #cbd5e1;
        margin-top: 4px;
    }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
        margin-bottom: 12px;
    }
    @media (min-width: 640px) {
        .kpi-grid {
            grid-template-columns: repeat(4, 1fr);
        }
    }
    .kpi-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 10px 12px;
    }
    .kpi-card.alert {
        background: #fef2f2;
        border-color: #fecaca;
    }
    .kpi-card.ok {
        background: #f0fdf4;
        border-color: #bbf7d0;
    }
    .kpi-label {
        font-size: 0.75rem;
        color: #64748b;
        margin-bottom: 2px;
    }
    .kpi-val {
        font-size: 1.15rem;
        font-weight: 700;
        color: #0f172a;
    }
    .kpi-card.alert .kpi-val {
        color: #b91c1c;
    }
    .kpi-card.ok .kpi-val {
        color: #15803d;
    }
    button[data-baseweb="tab"] {
        font-size: 0.88rem !important;
        padding-left: 10px !important;
        padding-right: 10px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_kpi_grid(items):
    cards_html = ['<div class="kpi-grid">']
    for label, val, stype in items:
        cls = f"kpi-card {stype}".strip()
        cards_html.append(
            f'<div class="{cls}"><div class="kpi-label">{label}</div><div class="kpi-val">{val}</div></div>'
        )
    cards_html.append("</div>")
    st.markdown("".join(cards_html), unsafe_allow_html=True)


def get_api_token() -> str:
    try:
        if "COC_API_TOKEN" in st.secrets:
            return str(st.secrets["COC_API_TOKEN"]).strip()
    except Exception:
        pass
    return os.getenv("COC_API_TOKEN", "").strip()


def parse_coc_time(ts: str):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_live_war(clan_tag: str, token: str) -> dict:
    encoded = urllib.parse.quote(clan_tag)
    url = f"{API_BASE}/clans/{encoded}/currentwar"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API 请求失败 ({resp.status_code}): {resp.text}")
    return resp.json()


def convert_gsheet_to_csv_url(url: str) -> str:
    url = url.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return url
    sheet_id = match.group(1)
    gid_match = re.search(r"[?&#]gid=([0-9]+)", url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


@st.cache_data(ttl=120)
def load_gsheet(url: str) -> pd.DataFrame:
    return pd.read_csv(convert_gsheet_to_csv_url(url))


def build_excel_bytes(df: pd.DataFrame, sheet_title: str = "漏打统计") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title

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

    cols = list(df.columns)
    for c_idx, col_name in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=c_idx, value=col_name)
        cell.fill = navy_fill
        cell.font = font_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[1].height = 26

    for r_idx, row in df.iterrows():
        excel_r = r_idx + 2
        status_val = str(row.get("状态", row.get("出勤状态", "")))
        is_severe = "严重" in status_val or "0刀" in status_val
        is_minor = "一般" in status_val or "差1刀" in status_val

        row_fill = severe_fill if is_severe else (minor_fill if is_minor else (zebra_fill if r_idx % 2 == 1 else white_fill))
        row_font = font_severe if is_severe else (font_minor if is_minor else font_data)

        for c_idx, col_name in enumerate(cols, start=1):
            val = row[col_name]
            cell = ws.cell(row=excel_r, column=c_idx, value=val)
            cell.fill = row_fill
            cell.font = row_font
            cell.border = border
            cell.alignment = Alignment(horizontal="left" if "成员" in col_name else "center", vertical="center")
            if col_name in ("状态", "出勤状态") and not is_severe and not is_minor:
                cell.fill = ok_fill
                cell.font = font_ok
        ws.row_dimensions[excel_r].height = 21

    for c_idx in range(1, len(cols) + 1):
        ws.column_dimensions[get_column_letter(c_idx)].width = 14
    ws.freeze_panes = "C2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


st.markdown(
    """
    <div class="clan-header">
        <div class="clan-title">⚔️ 萌面打劫 (#2YR9JVCG8) 部落战监控</div>
        <div class="clan-sub">实时催刀 · 自动归档历史 · 漏打红黄高亮</div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_live, tab_history, tab_clashperk = st.tabs([
    "🔴 实时催刀",
    "📊 自动归档",
    "📁 表格导入",
])

with tab_live:
    token = get_api_token()
    if not token:
        st.warning("尚未检测到 `COC_API_TOKEN`，请在 Streamlit App 设置的 Secrets 中填入官方 Token。")
    else:
        if st.button("🔄 刷新实时战况", use_container_width=True):
            st.cache_data.clear()

        try:
            war = fetch_live_war(CLAN_TAG, token)
            state = war.get("state", "notInWar")
            state_map = {
                "notInWar": "⚪ 当前未开战",
                "preparation": "🟡 备战日（准备中）",
                "inWar": "🔴 战斗日进行中",
                "warEnded": "🏁 本场已结束（结算中）",
            }
            st.markdown(f"**当前状态：{state_map.get(state, state)}**")

            if state == "notInWar":
                st.info("部落目前没有正在进行的常规部落战。开战后点刷新即可实时查看未出刀名单。")
            else:
                clan_info = war.get("clan", {})
                opp_info = war.get("opponent", {})
                team_size = war.get("teamSize", 0)
                atk_limit = war.get("attacksPerMember", 2)

                end_dt = parse_coc_time(war.get("endTime", ""))
                remain_str = "-"
                if end_dt:
                    diff = end_dt - datetime.now(timezone.utc)
                    if diff.total_seconds() > 0:
                        hrs = int(diff.total_seconds() // 3600)
                        mins = int((diff.total_seconds() % 3600) // 60)
                        remain_str = f"{hrs}h {mins}m"
                    else:
                        remain_str = "已结束"

                render_kpi_grid([
                    ("对战规模", f"{team_size} vs {team_size}", ""),
                    ("剩余时间", remain_str, "alert" if state == "inWar" else ""),
                    ("我方总星", f"{clan_info.get('stars', 0)} ★ ({clan_info.get('destructionPercentage', 0):.1f}%)", "ok"),
                    ("敌方总星", f"{opp_info.get('stars', 0)} ★ ({opp_info.get('destructionPercentage', 0):.1f}%)", ""),
                ])

                members = clan_info.get("members", [])
                live_rows = []
                for m in sorted(members, key=lambda x: x.get("mapPosition", 999)):
                    atks = m.get("attacks", []) or []
                    used = len(atks)
                    rem = max(0, atk_limit - used)
                    stars = sum(int(a.get("stars", 0)) for a in atks)
                    if rem == atk_limit:
                        st_label = "🔴 0刀"
                    elif rem > 0:
                        st_label = f"🟡 差{rem}刀"
                    else:
                        st_label = "🟢 已满"

                    live_rows.append({
                        "状态": st_label,
                        "位次": f"#{m.get('mapPosition', 0)}",
                        "成员名称": m.get("name", ""),
                        "出刀": f"{used}/{atk_limit}",
                        "剩余": rem,
                        "得星": stars,
                        "大本": m.get("townhallLevel", 0),
                    })

                live_df = pd.DataFrame(live_rows)
                live_df = live_df.sort_values(by=["剩余", "位次"], ascending=[False, True]).reset_index(drop=True)

                only_rem = st.checkbox("仅看还没打满的成员", value=False, key="live_only_rem")
                show_live = live_df[live_df["剩余"] > 0] if only_rem else live_df

                def style_live(r):
                    s = str(r["状态"])
                    if "🔴" in s:
                        return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                    elif "🟡" in s:
                        return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                    return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

                mobile_live_cols = ["状态", "位次", "成员名称", "出刀", "得星"]
                st.dataframe(
                    show_live[mobile_live_cols].style.apply(style_live, axis=1),
                    use_container_width=True,
                    height=460,
                    hide_index=True,
                )

                zero_df = live_df[live_df["剩余"] == atk_limit]
                one_df = live_df[(live_df["剩余"] > 0) & (live_df["剩余"] < atk_limit)]
                if state == "inWar" and (not zero_df.empty or not one_df.empty):
                    st.markdown("**📢 一键复制实时催刀通知**")
                    txt_lines = [
                        f"【萌面打劫 部落战催刀】剩余 {remain_str}",
                        f"比分：{clan_info.get('stars', 0)}★ vs {opp_info.get('stars', 0)}★",
                        "",
                    ]
                    if not zero_df.empty:
                        txt_lines.append("🔴 一刀未出：")
                        txt_lines.append("、".join(f"{r['位次']}{r['成员名称']}" for _, r in zero_df.iterrows()))
                        txt_lines.append("")
                    if not one_df.empty:
                        txt_lines.append("🟡 还剩 1 刀：")
                        txt_lines.append("、".join(f"{r['位次']}{r['成员名称']}" for _, r in one_df.iterrows()))
                    st.code("\n".join(txt_lines), language="text")
        except Exception as e:
            st.error(f"获取实时部落战失败：{e}")

with tab_history:
    if not os.path.exists(HISTORY_FILE):
        st.info(
            "💡 **为什么这里目前是空的？**\n\n"
            "本页数据来自仓库里的 `war_history.csv`（由 GitHub Actions 每 30 分钟抓拍官方接口自动生成）。\n"
            "1. 请先去 GitHub 仓库的 **Actions** 页面点击 **Run workflow** 手动触发首次同步；\n"
            "2. 官方接口仅记录从配置后开始的新场次，在自动攒够 15 场之前，请先点右侧 **「📁 表格导入」** 查看已有的 14 场历史汇总。"
        )
    else:
        hist_df = pd.read_csv(HISTORY_FILE)
        if hist_df.empty:
            st.info("`war_history.csv` 已创建，但当前部落尚未处于战斗日。开战后系统会自动录入每一场数据。")
        else:
            unique_wars = sorted(hist_df["war_id"].astype(str).unique().tolist())
            total_recorded = len(unique_wars)
            default_n = min(15, total_recorded)

            last_n = st.slider(
                f"统计最近几场（已自动归档 {total_recorded} 场）",
                min_value=1,
                max_value=max(1, total_recorded),
                value=default_n,
            )

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                only_miss_hist = st.checkbox("仅看漏打成员", value=False, key="hist_only_miss")
            with col_f2:
                show_full_cols = st.checkbox("展开详细星数列", value=False, key="hist_full_cols")

            target_war_ids = set(unique_wars[-last_n:])
            sub = hist_df[hist_df["war_id"].astype(str).isin(target_war_ids)].copy()

            grouped = (
                sub.groupby(["player_tag", "player_name"], as_index=False)
                .agg(
                    大本营=("town_hall", "max"),
                    参战场次=("war_id", "nunique"),
                    应出刀数=("attacks_per_member", "sum"),
                    实际出刀=("attacks_used", "sum"),
                    漏打刀数=("attacks_missed", "sum"),
                    总得星=("total_stars", "sum"),
                    三星数=("three_stars", "sum"),
                )
            )
            grouped["漏刀率(%)"] = (grouped["漏打刀数"] / grouped["应出刀数"] * 100).round(1)
            grouped["刀均得星"] = grouped.apply(
                lambda r: round(r["总得星"] / r["实际出刀"], 2) if r["实际出刀"] > 0 else 0.0, axis=1
            )
            grouped["三星率(%)"] = grouped.apply(
                lambda r: round(r["三星数"] / r["实际出刀"] * 100, 1) if r["实际出刀"] > 0 else 0.0, axis=1
            )
            grouped["出勤"] = grouped.apply(lambda r: f"{r['实际出刀']}/{r['应出刀数']}", axis=1)

            def tag_hist_status(r):
                if r["漏打刀数"] >= 6 or (r["漏打刀数"] > 0 and r["实际出刀"] == 0):
                    return "🔴 严重"
                elif r["漏打刀数"] > 0:
                    return "🟡 漏打"
                return "🟢 全勤"

            grouped["状态"] = grouped.apply(tag_hist_status, axis=1)
            grouped = grouped.sort_values(
                by=["漏打刀数", "漏刀率(%)", "参战场次", "总得星"],
                ascending=[False, False, False, False],
            ).reset_index(drop=True)
            grouped = grouped.rename(columns={"player_name": "成员名称", "player_tag": "玩家标签"})

            render_kpi_grid([
                ("统计场次", f"近 {len(target_war_ids)} 场", ""),
                ("全勤人数", f"{int((grouped['漏打刀数'] == 0).sum())} 人", "ok"),
                ("漏打人数", f"{int((grouped['漏打刀数'] > 0).sum())} 人", "alert"),
                ("累计漏刀", f"{int(grouped['漏打刀数'].sum())} 刀", "alert"),
            ])

            view_hist = grouped[grouped["漏打刀数"] > 0] if only_miss_hist else grouped

            compact_cols = ["状态", "成员名称", "出勤", "漏打刀数", "漏刀率(%)"]
            detail_cols = [
                "状态", "成员名称", "大本营", "参战场次", "出勤",
                "漏打刀数", "漏刀率(%)", "总得星", "刀均得星", "三星率(%)"
            ]
            use_cols = detail_cols if show_full_cols else compact_cols

            def style_hist(r):
                s = str(r["状态"])
                if "严重" in s:
                    return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                elif "漏打" in s:
                    return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

            fmt_dict = {"漏刀率(%)": "{:.1f}%"}
            if show_full_cols:
                fmt_dict.update({"三星率(%)": "{:.1f}%", "刀均得星": "{:.2f}"})

            st.dataframe(
                view_hist[use_cols].style.apply(style_hist, axis=1).format(fmt_dict),
                use_container_width=True,
                height=480,
                hide_index=True,
            )

            st.download_button(
                label=f"⬇️ 下载最近{len(target_war_ids)}场出勤表 (.xlsx)",
                data=build_excel_bytes(view_hist[detail_cols], f"最近{len(target_war_ids)}场统计"),
                file_name=f"萌面打劫_最近{len(target_war_ids)}场出勤统计.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            sev = grouped[grouped["状态"].str.contains("严重")]
            min_l = grouped[grouped["状态"].str.contains("漏打")]
            msg = [
                f"【萌面打劫 近{len(target_war_ids)}场部落战通报】",
                f"全勤 {int((grouped['漏打刀数'] == 0).sum())} 人 | 漏打 {int((grouped['漏打刀数'] > 0).sum())} 人（共漏 {int(grouped['漏打刀数'].sum())} 刀）",
                "",
                "🔴 严重漏打 / 全鸽名单：",
            ]
            for _, r in sev.iterrows():
                msg.append(f"- {r['成员名称']}：漏 {r['漏打刀数']} 刀（出勤 {r['出勤']}，漏刀率 {r['漏刀率(%)']}%）")
            msg.append("")
            msg.append("🟡 一般漏打提醒：")
            for _, r in min_l.iterrows():
                msg.append(f"- {r['成员名称']}：漏 {r['漏打刀数']} 刀（出勤 {r['出勤']}）")
            st.markdown("**📢 一键复制群通知**")
            st.code("\n".join(msg), language="text")

with tab_clashperk:
    gs_url = st.text_input("ClashPerk Google Sheet 链接", value=DEFAULT_SHEET_URL)
    col_cp1, col_cp2 = st.columns(2)
    with col_cp1:
        cp_only_miss = st.checkbox("仅看漏打成员", value=False, key="cp_only_miss")
    with col_cp2:
        cp_full_cols = st.checkbox("展开详细星数列", value=False, key="cp_full_cols")

    if gs_url:
        try:
            cp_raw = load_gsheet(gs_url).dropna(subset=["Name"]).copy()
            cp_raw["Wars Participated"] = cp_raw["Wars Participated"].astype(int)
            cp_raw["Number of Attacks"] = cp_raw["Number of Attacks"].astype(int)
            cp_raw["Missed"] = cp_raw["Missed"].astype(int)
            cp_raw["应出刀数"] = cp_raw["Wars Participated"] * 2
            cp_raw["漏刀率(%)"] = (cp_raw["Missed"] / cp_raw["应出刀数"] * 100).round(1)
            cp_raw["出勤"] = cp_raw.apply(lambda r: f"{r['Number of Attacks']}/{r['应出刀数']}", axis=1)
            cp_raw["状态"] = cp_raw.apply(
                lambda r: "🔴 严重"
                if (r["Missed"] >= 6 or (r["Missed"] > 0 and r["Number of Attacks"] == 0))
                else ("🟡 漏打" if r["Missed"] > 0 else "🟢 全勤"),
                axis=1,
            )
            cp_sorted = cp_raw.sort_values(by=["Missed", "漏刀率(%)"], ascending=[False, False]).reset_index(drop=True)
            cp_sorted = cp_sorted.rename(
                columns={
                    "Name": "成员名称",
                    "Tag": "玩家标签",
                    "Wars Participated": "参战场次",
                    "Number of Attacks": "实际出刀",
                    "Missed": "漏打刀数",
                    "Total Stars": "总得星",
                    "Avg. Stars": "刀均得星",
                }
            )

            render_kpi_grid([
                ("收录人数", f"{len(cp_sorted)} 人", ""),
                ("全勤人数", f"{int((cp_sorted['漏打刀数'] == 0).sum())} 人", "ok"),
                ("漏打人数", f"{int((cp_sorted['漏打刀数'] > 0).sum())} 人", "alert"),
                ("累计漏刀", f"{int(cp_sorted['漏打刀数'].sum())} 刀", "alert"),
            ])

            cp_view = cp_sorted[cp_sorted["漏打刀数"] > 0] if cp_only_miss else cp_sorted
            cp_compact = ["状态", "成员名称", "出勤", "漏打刀数", "漏刀率(%)"]
            cp_detail = ["状态", "成员名称", "参战场次", "出勤", "漏打刀数", "漏刀率(%)", "总得星", "刀均得星"]
            cp_cols = cp_detail if cp_full_cols else cp_compact

            def style_cp(r):
                s = str(r["状态"])
                if "严重" in s:
                    return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                elif "漏打" in s:
                    return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

            cp_fmt = {"漏刀率(%)": "{:.1f}%"}
            if cp_full_cols:
                cp_fmt["刀均得星"] = "{:.2f}"

            st.dataframe(
                cp_view[cp_cols].style.apply(style_cp, axis=1).format(cp_fmt),
                use_container_width=True,
                height=480,
                hide_index=True,
            )

            st.download_button(
                label="⬇️ 下载高亮统计表 (.xlsx)",
                data=build_excel_bytes(cp_view[cp_detail], "ClashPerk统计"),
                file_name="萌面打劫_部落战出勤统计.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"加载 Google Sheet 失败：{e}")
