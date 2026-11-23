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
    page_title="萌面打劫 | 部落战全自动出勤监控",
    page_icon="⚔️",
    layout="wide",
)

CLAN_TAG = "#2YR9JVCG8"
API_BASE = "https://cocproxy.royaleapi.dev/v1"
HISTORY_FILE = "war_history.csv"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1GYL8qHNSyG8rGXycw_mbYIy-BuCpxlYPfYH7aYTvwPg/edit?gid=0#gid=0"


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
        status_val = str(row.get("出勤状态", ""))
        is_severe = "严重" in status_val or "未出刀" in status_val
        is_minor = "一般" in status_val or "差1刀" in status_val

        row_fill = severe_fill if is_severe else (minor_fill if is_minor else (zebra_fill if r_idx % 2 == 1 else white_fill))
        row_font = font_severe if is_severe else (font_minor if is_minor else font_data)

        for c_idx, col_name in enumerate(cols, start=1):
            val = row[col_name]
            cell = ws.cell(row=excel_r, column=c_idx, value=val)
            cell.fill = row_fill
            cell.font = row_font
            cell.border = border
            cell.alignment = Alignment(horizontal="left" if "名称" in col_name else "center", vertical="center")
            if col_name == "出勤状态" and not is_severe and not is_minor:
                cell.fill = ok_fill
                cell.font = font_ok
        ws.row_dimensions[excel_r].height = 21

    for c_idx in range(1, len(cols) + 1):
        ws.column_dimensions[get_column_letter(c_idx)].width = 15
    ws.freeze_panes = "C2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


st.title("⚔️ 萌面打劫 (#2YR9JVCG8) — 部落战全自动监控台")
st.caption("支持直连 Supercell 官方接口实时催刀、GitHub Actions 自动累计历史场次，以及 ClashPerk 历史数据导入")

tab_live, tab_history, tab_clashperk = st.tabs([
    "🔴 实时部落战（当前催刀）",
    "📊 自动归档统计（最近15场）",
    "📁 ClashPerk 表格导入（备用）",
])

with tab_live:
    token = get_api_token()
    if not token:
        st.warning(
            "尚未检测到 `COC_API_TOKEN`。请在 Streamlit App 设置的 **Secrets** 中添加 "
            '`COC_API_TOKEN = "你的Supercell_API_Key"` 即可开启实时战况与自动抓拍。'
        )
    else:
        col_btn, _ = st.columns([1, 4])
        with col_btn:
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
            st.subheader(f"当前状态：{state_map.get(state, state)}")

            if state == "notInWar":
                st.info("部落目前没有正在进行的常规部落战。开战后刷新此页面即可实时查看未出刀名单。")
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
                        remain_str = f"{hrs} 小时 {mins} 分钟"
                    else:
                        remain_str = "已结束"

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("对战规模", f"{team_size} vs {team_size}")
                m2.metric("我方总星 / 摧毁率", f"{clan_info.get('stars', 0)} ★ ({clan_info.get('destructionPercentage', 0):.1f}%)")
                m3.metric("敌方总星 / 摧毁率", f"{opp_info.get('stars', 0)} ★ ({opp_info.get('destructionPercentage', 0):.1f}%)")
                m4.metric("距离结束剩余", remain_str)

                members = clan_info.get("members", [])
                live_rows = []
                for m in sorted(members, key=lambda x: x.get("mapPosition", 999)):
                    atks = m.get("attacks", []) or []
                    used = len(atks)
                    rem = max(0, atk_limit - used)
                    stars = sum(int(a.get("stars", 0)) for a in atks)
                    if rem == atk_limit:
                        st_label = "🔴 0刀未出"
                    elif rem > 0:
                        st_label = f"🟡 差{rem}刀"
                    else:
                        st_label = "🟢 已出满"

                    live_rows.append({
                        "出勤状态": st_label,
                        "编号": m.get("mapPosition", 0),
                        "成员名称": m.get("name", ""),
                        "玩家标签": m.get("tag", ""),
                        "大本营": m.get("townhallLevel", 0),
                        "已出刀": used,
                        "剩余刀数": rem,
                        "本场得星": stars,
                    })

                live_df = pd.DataFrame(live_rows)
                live_df = live_df.sort_values(by=["剩余刀数", "编号"], ascending=[False, True]).reset_index(drop=True)

                def style_live(r):
                    s = str(r["出勤状态"])
                    if "🔴" in s:
                        return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                    elif "🟡" in s:
                        return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                    return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

                st.dataframe(
                    live_df.style.apply(style_live, axis=1),
                    use_container_width=True,
                    height=520,
                    hide_index=True,
                )

                zero_df = live_df[live_df["已出刀"] == 0]
                one_df = live_df[(live_df["已出刀"] > 0) & (live_df["剩余刀数"] > 0)]
                if state == "inWar" and (not zero_df.empty or not one_df.empty):
                    st.subheader("📢 一键复制实时催刀通知")
                    txt_lines = [
                        f"【萌面打劫 部落战催刀提醒】距离结束还剩 {remain_str}",
                        f"当前比分：{clan_info.get('stars', 0)} ★ vs {opp_info.get('stars', 0)} ★",
                        "",
                    ]
                    if not zero_df.empty:
                        txt_lines.append("🔴 一刀未出（请尽快上线出刀）：")
                        txt_lines.append("、".join(f"#{r['编号']} {r['成员名称']}" for _, r in zero_df.iterrows()))
                        txt_lines.append("")
                    if not one_df.empty:
                        txt_lines.append("🟡 还剩 1 刀（记得补刀）：")
                        txt_lines.append("、".join(f"#{r['编号']} {r['成员名称']}" for _, r in one_df.iterrows()))
                    st.code("\n".join(txt_lines), language="text")
        except Exception as e:
            st.error(f"获取实时部落战失败：{e}")

with tab_history:
    if not os.path.exists(HISTORY_FILE):
        st.info("`war_history.csv` 尚未生成。配置好 GitHub Actions 定时任务后，每场部落战结束都会自动写入此文件。")
    else:
        hist_df = pd.read_csv(HISTORY_FILE)
        if hist_df.empty:
            st.info("历史存档暂无记录，等待当前或下一场部落战开始后即可自动记录。")
        else:
            unique_wars = sorted(hist_df["war_id"].astype(str).unique().tolist())
            total_recorded = len(unique_wars)
            default_n = min(15, total_recorded)

            c_slider, c_check = st.columns([2, 1])
            with c_slider:
                last_n = st.slider(
                    f"选择统计最近几场部落战（当前库内共已存档 {total_recorded} 场）",
                    min_value=1,
                    max_value=max(1, total_recorded),
                    value=default_n,
                )
            with c_check:
                st.write("")
                only_miss_hist = st.checkbox("仅显示有漏打成员", value=False, key="hist_only_miss")

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

            def tag_hist_status(r):
                if r["漏打刀数"] >= 6 or (r["漏打刀数"] > 0 and r["实际出刀"] == 0):
                    return "🔴 严重漏打"
                elif r["漏打刀数"] > 0:
                    return "🟡 一般漏打"
                return "🟢 全勤"

            grouped["出勤状态"] = grouped.apply(tag_hist_status, axis=1)
            grouped = grouped.sort_values(
                by=["漏打刀数", "漏刀率(%)", "参战场次", "总得星"],
                ascending=[False, False, False, False],
            ).reset_index(drop=True)

            cols_order = [
                "出勤状态", "player_name", "player_tag", "大本营",
                "参战场次", "应出刀数", "实际出刀", "漏打刀数", "漏刀率(%)",
                "总得星", "刀均得星", "三星数", "三星率(%)"
            ]
            grouped = grouped[cols_order].rename(columns={"player_name": "成员名称", "player_tag": "玩家标签"})

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("统计场次", f"最近 {len(target_war_ids)} 场")
            k2.metric("全勤人数", f"{int((grouped['漏打刀数'] == 0).sum())} 人")
            k3.metric("漏打人数", f"{int((grouped['漏打刀数'] > 0).sum())} 人")
            k4.metric("累计漏打刀数", f"{int(grouped['漏打刀数'].sum())} 刀")

            view_hist = grouped[grouped["漏打刀数"] > 0] if only_miss_hist else grouped

            def style_hist(r):
                s = str(r["出勤状态"])
                if "严重" in s:
                    return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                elif "一般" in s:
                    return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

            st.dataframe(
                view_hist.style.apply(style_hist, axis=1).format({
                    "漏刀率(%)": "{:.1f}%",
                    "三星率(%)": "{:.1f}%",
                    "刀均得星": "{:.2f}",
                }),
                use_container_width=True,
                height=520,
                hide_index=True,
            )

            col_dl, col_txt = st.columns([1, 1.4])
            with col_dl:
                st.download_button(
                    label=f"⬇️ 下载最近{len(target_war_ids)}场出勤表 (.xlsx)",
                    data=build_excel_bytes(view_hist, f"最近{len(target_war_ids)}场统计"),
                    file_name=f"萌面打劫_最近{len(target_war_ids)}场出勤统计.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            with col_txt:
                sev = grouped[grouped["出勤状态"].str.contains("严重")]
                min_l = grouped[grouped["出勤状态"].str.contains("一般")]
                msg = [
                    f"【萌面打劫 最近 {len(target_war_ids)} 场部落战出勤通报】",
                    f"全勤 {int((grouped['漏打刀数'] == 0).sum())} 人 | 漏打 {int((grouped['漏打刀数'] > 0).sum())} 人（累计漏 {int(grouped['漏打刀数'].sum())} 刀）",
                    "",
                    "🔴 严重漏打 / 全鸽名单：",
                ]
                for _, r in sev.iterrows():
                    msg.append(f"- {r['成员名称']}：漏 {r['漏打刀数']} 刀（出刀 {r['实际出刀']}/{r['应出刀数']}，漏刀率 {r['漏刀率(%)']}%）")
                msg.append("")
                msg.append("🟡 一般漏打提醒：")
                for _, r in min_l.iterrows():
                    msg.append(f"- {r['成员名称']}：漏 {r['漏打刀数']} 刀（出刀 {r['实际出刀']}/{r['应出刀数']}）")
                st.code("\n".join(msg), language="text")

with tab_clashperk:
    st.write("在新数据库攒够 15 场之前，可继续在此处粘贴 ClashPerk 导出的 Google Sheet 链接查看历史记录。")
    gs_url = st.text_input("ClashPerk Google Sheet 链接", value=DEFAULT_SHEET_URL)
    if gs_url:
        try:
            cp_raw = load_gsheet(gs_url).dropna(subset=["Name"]).copy()
            cp_raw["应出刀数"] = cp_raw["Wars Participated"].astype(int) * 2
            cp_raw["漏刀率(%)"] = (cp_raw["Missed"].astype(int) / cp_raw["应出刀数"] * 100).round(1)
            cp_raw["出勤状态"] = cp_raw.apply(
                lambda r: "🔴 严重漏打"
                if (int(r["Missed"]) >= 6 or (int(r["Missed"]) > 0 and int(r["Number of Attacks"]) == 0))
                else ("🟡 一般漏打" if int(r["Missed"]) > 0 else "🟢 全勤"),
                axis=1,
            )
            cp_sorted = cp_raw.sort_values(by=["Missed", "漏刀率(%)"], ascending=[False, False]).reset_index(drop=True)
            cp_view = cp_sorted[
                ["出勤状态", "Name", "Tag", "Wars Participated", "应出刀数", "Number of Attacks", "Missed", "漏刀率(%)", "Total Stars", "Avg. Stars"]
            ].rename(
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

            def style_cp(r):
                s = str(r["出勤状态"])
                if "严重" in s:
                    return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                elif "一般" in s:
                    return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

            st.dataframe(
                cp_view.style.apply(style_cp, axis=1).format({"漏刀率(%)": "{:.1f}%", "刀均得星": "{:.2f}"}),
                use_container_width=True,
                height=500,
                hide_index=True,
            )
        except Exception as e:
            st.error(f"加载 Google Sheet 失败：{e}")
