from collections.abc import Callable

import streamlit as st


_GRID_HTML = """
<div class="grid-shell">
  <table>
    <thead><tr id="grid-head"></tr></thead>
    <tbody id="grid-body"></tbody>
  </table>
</div>
"""

_GRID_CSS = """
:host { color: var(--st-text-color); font-family: var(--st-font); }
.grid-shell { border: 1px solid var(--st-dataframe-border-color); border-radius: var(--st-base-radius); overflow-x: auto; }
table { border-collapse: separate; border-spacing: 0; min-width: 1050px; width: 100%; font-size: .875rem; }
th, td { border-bottom: 1px solid var(--st-dataframe-border-color); padding: 6px 8px; text-align: left; vertical-align: middle; white-space: nowrap; }
th { background: var(--st-dataframe-header-background-color); font-weight: 600; position: sticky; top: 0; z-index: 2; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: color-mix(in srgb, var(--st-secondary-background-color) 55%, transparent); }
.project { min-width: 170px; position: sticky; left: 0; z-index: 1; background: var(--st-background-color); }
.task { min-width: 145px; position: sticky; left: 186px; z-index: 1; background: var(--st-background-color); }
th.project, th.task { z-index: 3; background: var(--st-dataframe-header-background-color); }
.day { min-width: 92px; text-align: center; }
.total { min-width: 70px; text-align: right; font-weight: 600; }
.stepper { display: grid; grid-template-columns: 24px minmax(42px, 1fr) 24px; align-items: stretch; height: 30px; }
.stepper button, .remove { border: 1px solid var(--st-widget-border-color); background: var(--st-secondary-background-color); color: var(--st-text-color); cursor: pointer; font: inherit; }
.stepper button:first-child { border-radius: var(--st-button-radius) 0 0 var(--st-button-radius); }
.stepper button:last-child { border-radius: 0 var(--st-button-radius) var(--st-button-radius) 0; }
.stepper button:hover, .remove:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
.stepper input { min-width: 0; width: 100%; box-sizing: border-box; border: solid var(--st-widget-border-color); border-width: 1px 0; border-radius: 0; background: var(--st-background-color); color: var(--st-text-color); text-align: center; font: inherit; }
.stepper input[type="number"] { appearance: textfield; -moz-appearance: textfield; }
.stepper input[type="number"]::-webkit-inner-spin-button,
.stepper input[type="number"]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.stepper input:focus { outline: 2px solid var(--st-primary-color); outline-offset: -2px; }
.stepper button:disabled, .stepper input:disabled, .remove:disabled { cursor: not-allowed; opacity: .55; }
.remove { border-radius: var(--st-button-radius); width: 30px; height: 30px; }
.details { min-width: 150px; }
.details input[type="text"] { width: 100%; min-width: 130px; box-sizing: border-box; border: 1px solid var(--st-widget-border-color); border-radius: var(--st-base-radius); background: var(--st-background-color); color: var(--st-text-color); padding: 5px 7px; font: inherit; }
.classification { color: var(--st-gray-text-color); }
"""

_GRID_JS = """
export default function(component) {
  const { data, parentElement, setTriggerValue } = component
  const head = parentElement.querySelector("#grid-head")
  const body = parentElement.querySelector("#grid-body")
  if (!head || !body) return

  const el = (tag, className, text) => {
    const node = document.createElement(tag)
    if (className) node.className = className
    if (text !== undefined) node.textContent = text
    return node
  }
  const emit = payload => setTriggerValue("action", payload)
  const headers = ["Project / category", "Task / work code"]
  if (data.showDetails) {
    headers.push("Class", "Notes")
    if (data.showHandsOn) headers.push("Hands-on")
  }
  headers.push(...data.days, "Total", "")
  head.replaceChildren(...headers.map((label, index) => {
    const className = index === 0 ? "project" : index === 1 ? "task" :
      (label === "Total" ? "total" : (data.days.includes(label) ? "day" : "details"))
    return el("th", className, label)
  }))

  const rows = data.rows.map(row => {
    const tr = el("tr")
    tr.append(el("td", "project", row.project), el("td", "task", row.task))
    if (data.showDetails) {
      tr.append(el("td", "classification", row.classification))
      const noteCell = el("td", "details")
      const note = el("input")
      note.type = "text"
      note.value = row.notes
      note.disabled = !data.editable
      note.setAttribute("aria-label", `Notes for ${row.project} ${row.task}`)
      note.onchange = event => emit({type: "notes", rowId: row.id, notes: event.target.value})
      noteCell.append(note)
      tr.append(noteCell)
      if (data.showHandsOn) {
        const handsCell = el("td", "day")
        if (row.managerOversight) {
          const hands = el("input")
          hands.type = "checkbox"
          hands.checked = row.handsOn
          hands.disabled = !data.editable
          hands.setAttribute("aria-label", `Hands-on capital for ${row.project} ${row.task}`)
          hands.onchange = event => emit({type: "handsOn", rowId: row.id, value: event.target.checked})
          handsCell.append(hands)
        }
        tr.append(handsCell)
      }
    }

    const hourCells = []
    row.hours.forEach((hours, offset) => {
      const td = el("td", "day")
      const stepper = el("div", "stepper")
      const minus = el("button", "", "−")
      const input = el("input")
      const plus = el("button", "", "+")
      input.type = "number"
      input.min = "0"
      input.max = String(data.maxHours)
      input.step = "0.25"
      input.value = Number(hours).toFixed(2)
      input.disabled = minus.disabled = plus.disabled = !data.editable
      input.setAttribute("aria-label", `${data.days[offset]} hours for ${row.project} ${row.task}`)
      const commit = value => {
        const next = Math.min(data.maxHours, Math.max(0, Math.round(Number(value) * 4) / 4))
        input.value = next.toFixed(2)
        emit({type: "hours", rowId: row.id, offset, value: next})
      }
      minus.onclick = () => commit(Number(input.value) - .25)
      plus.onclick = () => commit(Number(input.value) + .25)
      input.onchange = () => commit(input.value)
      stepper.append(minus, input, plus)
      td.append(stepper)
      hourCells.push(td)
    })
    tr.append(...hourCells)
    tr.append(el("td", "total", `${row.hours.reduce((sum, value) => sum + Number(value), 0).toFixed(2)} h`))
    const actionCell = el("td")
    const remove = el("button", "remove", "×")
    remove.disabled = !data.editable
    remove.title = "Remove row"
    remove.setAttribute("aria-label", `Remove ${row.project} ${row.task}`)
    remove.onclick = () => emit({type: "remove", rowId: row.id})
    actionCell.append(remove)
    tr.append(actionCell)
    return tr
  })
  body.replaceChildren(...rows)
}
"""

_TIMESHEET_GRID = st.components.v2.component(
    "time_tracker.timesheet_grid",
    html=_GRID_HTML,
    css=_GRID_CSS,
    js=_GRID_JS,
)


def timesheet_grid(
    *,
    rows: list[dict],
    days: list[str],
    editable: bool,
    show_details: bool,
    max_hours: float,
    key: str,
    on_action_change: Callable[[], None] | None = None,
):
    return _TIMESHEET_GRID(
        key=key,
        data={
            "rows": rows,
            "days": days,
            "editable": editable,
            "showDetails": show_details,
            "showHandsOn": any(row.get("managerOversight") for row in rows),
            "maxHours": max_hours,
        },
        on_action_change=on_action_change or (lambda: None),
        width="stretch",
    )
