/**
 * 工作台「最近记录」与眼底页「筛查历史」共用的一行记录。
 * 图标按类型区分；没有 DR 分级的记录（化验单、症状）显示摘要，而不是一个孤零零的「–」。
 */
import { esc, svg } from "@/lib/icons";
import { fmtTime, URG_TEXT, type MedRecord } from "@/stores/records";

const REC_ICON: Record<string, string> = { 眼底彩照: "eye", 化验单: "lab", 症状描述: "chat" };

export function recordRowHtml(r: MedRecord): string {
  const title = r.level != null ? `${r.input_type} · DR ${r.level} 级` : r.input_type;
  const sum = (r.summary || "").replace(/\s+/g, " ").trim();
  return (
    `<div class="rec"><div class="ic-plate">${svg(REC_ICON[r.input_type] ?? "xray")}</div>` +
    `<div class="meta"><b>${esc(title)}</b><span class="rr"><time>${esc(fmtTime(r.created_at))}</time>` +
    `${sum ? `<em>${esc(sum)}</em>` : ""}</span></div>` +
    `<div class="res"><span class="gem ${r.urgency || "green"}"></span>${esc(URG_TEXT[r.urgency] ?? "常规")} · ${esc(r.department)}</div></div>`
  );
}
