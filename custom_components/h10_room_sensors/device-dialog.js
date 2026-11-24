const PARAMETER = "h10_room_sensors";
const DEVICE_PATH = /^\/config\/devices\/device\/([\w-]+)\/?$/;
const NAMESPACE = "h10_room_sensors/device/";
const TAG = "h10-room-sensors-dialog";
let opening = false;

const messages = {
  de: {
    sensors: "Raumfühler", circuit: "Heizkreis", unassigned: "Kein Raumfühler",
    missing: "Fühler nicht verfügbar", waiting: "Wartet auf Raumfühler",
    busy: "Zuordnung wird geändert", rejected: "Zigbee-Anfrage abgelehnt",
    linked: "Binding bestätigt", temperature: "Istwert am H10",
    noReading: "Messwert ausstehend", unavailable: "H10 nicht erreichbar",
    save: "Zuordnungen speichern", retry: "Erneut versuchen", restore: "Erneut verbinden", close: "Schließen",
    hint: "Derselbe Fühler kann mehrere Heizkreise versorgen. Bei Bedarf wartet Home Assistant, bis der Fühler sich meldet.",
    saved: "Änderungen gespeichert.", refresh: "Istwerte aktualisieren",
    openingError: "Home Assistant ist noch nicht verbunden. Lade die Seite neu.",
    diagnostic: "Zigbee-Bindings prüfen", readBindings: "Binding-Tabelle lesen",
    checkingBindings: "Lese Binding-Tabelle …", bindingsChanged: "Die Tabelle hat sich geändert. Lies sie erneut.",
    presentBindings: "Im Fühler gespeichert", missingBindings: "Zugeordnet, aber nicht in der Tabelle",
    diagnosticHint: "Drücke beim Lesen kurz die Taste eines batteriebetriebenen Fühlers.",
    coordinatorBinding: "Temperatur-Binding zum HA-Koordinator", yes: "Ja", no: "Nein",
  },
  en: {
    sensors: "Room sensors", circuit: "Heating circuit", unassigned: "No room sensor",
    missing: "Sensor unavailable", waiting: "Waiting for room sensor",
    busy: "Changing assignment", rejected: "Zigbee request rejected",
    linked: "Binding confirmed", temperature: "Temperature at the H10",
    noReading: "Waiting for a reading", unavailable: "H10 unavailable",
    save: "Save assignments", retry: "Try again", restore: "Reconnect", close: "Close",
    hint: "One sensor can serve several circuits. Home Assistant waits for the sensor to check in if needed.",
    saved: "Changes saved.", refresh: "Refresh temperatures",
    openingError: "Home Assistant is still connecting. Reload the page.",
    diagnostic: "Check Zigbee bindings", readBindings: "Read binding table",
    checkingBindings: "Reading binding table …", bindingsChanged: "The table changed. Read it again.",
    presentBindings: "Stored on the sensor", missingBindings: "Assigned but missing from table",
    diagnosticHint: "Press the button on a battery-powered sensor while reading.",
    coordinatorBinding: "Temperature binding to the HA coordinator", yes: "Yes", no: "No",
  },
};

function targetOf(value) {
  const url = new URL(value, location.href);
  const path = url.origin === location.origin && DEVICE_PATH.exec(url.pathname);
  return path && url.searchParams.get(PARAMETER) === "1" ? { id: path[1], url } : null;
}

class RoomSensorDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  set hass(value) {
    this._hass = value;
  }

  call(action, fields = {}) {
    return this._hass.callWS({
      type: NAMESPACE + action,
      device_id: this.snapshot.device_id,
      ...fields,
    });
  }

  showDialog(snapshot) {
    clearInterval(this.timer);
    this.snapshot = snapshot;
    this.drafts = new Map();
    this.rows = new Map();
    this.readings = new Map();
    this.opened = Symbol();
    this.saving = false;
    this.reading = false;
    this.lastRead = 0;
    this.diagnosing = false;
    this.refreshing = false;
    this.messages = this._hass.language?.startsWith("de") ? messages.de : messages.en;
    const t = this.messages;
    this.shadowRoot.innerHTML = `<style>
      ha-dialog { --ha-dialog-width-md: 650px; }
      .body { max-height: min(61dvh, 540px); overflow: auto; padding: 0 2px; }
      p { margin: 0 0 16px; color: var(--secondary-text-color); }
      #rows { border-top: 1px solid var(--divider-color); }
      .row {
        display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.35fr); gap: 12px 20px;
        align-items: center; padding: 12px 0; border-bottom: 1px solid var(--divider-color);
      }
      label { font-weight: 500; }
      small { display: block; color: var(--secondary-text-color); margin-top: 2px; }
      .controls { display: flex; flex-direction: column; align-items: stretch; gap: 6px; }
      select {
        min-height: 40px; width: 100%; font: inherit; padding: 6px 10px;
        color: var(--primary-text-color); background: var(--card-background-color);
        border: 1px solid var(--divider-color); border-radius: 8px;
      }
      select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
      .rejected, #notice[data-error] { color: var(--error-color); }
      #notice { min-height: 1.4em; margin: 10px 0 0; }
      #refresh { margin-bottom: 8px; }
      details { margin-top: 12px; }
      summary { cursor: pointer; color: var(--primary-color); }
      .diagnostic-controls { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
      #diagnose-sensor { max-width: 240px; }
      #diagnostic-result { line-height: 1.5; white-space: pre-line; }
      .footer { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; padding-top: 12px; }
      @media (max-width: 480px) { .row { grid-template-columns: 1fr; gap: 6px; } }
    </style>
    <ha-dialog open>
      <div class="body">
        <p id="hint"></p>
        <ha-button id="refresh"></ha-button>
        <div id="rows"></div>
        <details>
          <summary id="diagnostic"></summary>
          <div class="diagnostic-controls">
            <select id="diagnose-sensor"></select>
            <ha-button id="diagnose" appearance="outlined"></ha-button>
          </div>
          <small id="diagnostic-hint"></small>
          <small id="diagnostic-result" role="status"></small>
        </details>
        <p id="notice" role="status"></p>
      </div>
      <div class="footer">
        <ha-button id="close" variant="neutral" appearance="plain"></ha-button>
        <ha-button id="save" variant="brand" appearance="filled"></ha-button>
      </div>
    </ha-dialog>`;
    this.dialog = this.shadowRoot.querySelector("ha-dialog");
    this.dialog.heading = `${snapshot.name} · ${t.sensors}`;
    this.dialog.headerTitle = this.dialog.heading;
    this.dialog.setAttribute("header-title", this.dialog.heading);
    this.dialog.addEventListener("closed", () => this.closeDialog());
    for (const [id, label] of Object.entries({
      hint: t.hint, refresh: t.refresh, close: t.close, save: t.save,
      diagnostic: t.diagnostic, diagnose: t.readBindings, "diagnostic-hint": t.diagnosticHint,
    })) {
      this.shadowRoot.getElementById(id).textContent = label;
    }
    this.shadowRoot.getElementById("close").onclick = () => this.closeDialog();
    this.shadowRoot.getElementById("save").onclick = () => this.save();
    this.shadowRoot.getElementById("refresh").onclick = () => this.readTemperatures();
    const diagnoseSensor = this.shadowRoot.getElementById("diagnose-sensor");
    diagnoseSensor.setAttribute("aria-label", t.sensors);
    diagnoseSensor.onchange = () => { this.shadowRoot.getElementById("diagnostic-result").textContent = ""; };
    this.shadowRoot.getElementById("diagnose").onclick = () => this.readBindings();
    this.diagnosticChoices = null;
    this.update();
    this.timer = setInterval(() => this.poll(), 2500);
    this.readTemperatures();
  }

  closeDialog() {
    if (!this.opened) return true;
    this.opened = null;
    clearInterval(this.timer);
    this.dialog.open = false;
    this.dispatchEvent(new CustomEvent("dialog-closed", {
      bubbles: true, composed: true, detail: { dialog: TAG },
    }));
    return true;
  }

  disconnectedCallback() {
    this.opened = null;
    clearInterval(this.timer);
  }

  makeRow(circuit) {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = '<div><label></label><small class="status"></small><small class="reading"></small></div><div class="controls"><select></select><ha-button hidden size="s" appearance="plain"></ha-button></div>';
    const label = row.querySelector("label");
    const select = row.querySelector("select");
    label.textContent = `${this.messages.circuit} ${circuit}`;
    select.id = `circuit-${circuit}`;
    label.htmlFor = select.id;
    const retry = row.querySelector("ha-button");
    retry.textContent = this.messages.retry;
    retry.onclick = () => {
      const current = this.snapshot.circuits.find(item => item.circuit === circuit);
      this.save([{ circuit, expected: current.sensor, sensor: current.sensor }]);
    };
    select.onchange = () => {
      const current = this.snapshot.circuits.find(item => item.circuit === circuit);
      const sensor = select.value || null;
      if (sensor === current.sensor) this.drafts.delete(circuit);
      else {
        const expected = this.drafts.has(circuit) ? this.drafts.get(circuit).expected : current.sensor;
        this.drafts.set(circuit, { circuit, expected, sensor });
      }
      this.update();
    };
    this.shadowRoot.getElementById("rows").append(row);
    return { select, retry, status: row.querySelector(".status"), reading: row.querySelector(".reading") };
  }

  update() {
    const t = this.messages;
    for (const circuit of this.snapshot.circuits) {
      const id = circuit.circuit;
      if (!this.rows.has(id)) this.rows.set(id, this.makeRow(id));
      const row = this.rows.get(id);
      const draft = this.drafts.get(id);
      const selected = (draft ? draft.sensor : circuit.sensor) ?? "";
      const choices = [["", t.unassigned], ...Object.entries(this.snapshot.sensors)];
      if (selected && !Object.hasOwn(this.snapshot.sensors, selected)) {
        choices.push([selected, t.missing]);
      }
      const signature = JSON.stringify(choices);
      if (row.choices !== signature) {
        row.select.replaceChildren(...choices.map(([value, label]) => new Option(label, value)));
        row.choices = signature;
      }
      row.select.value = selected;
      row.select.disabled = this.saving || circuit.busy;
      row.status.classList.toggle("rejected", circuit.error === "rejected");
      row.status.textContent = circuit.busy ? t.busy
        : circuit.error === "rejected" ? t.rejected
        : circuit.pending ? t.waiting : circuit.applied ? t.linked : "";
      row.retry.textContent = circuit.error === "rejected" ? t.retry : t.restore;
      row.retry.hidden = Boolean(draft) || (circuit.error !== "rejected" && (!circuit.applied || circuit.pending));
      row.retry.disabled = this.saving || circuit.busy;
      const reading = this.readings.get(id);
      row.reading.textContent = circuit.applied
        ? (reading === undefined || reading === null ? t.noReading
          : reading === false ? t.unavailable
          : `${t.temperature} ${new Intl.NumberFormat(this._hass.language, {maximumFractionDigits: 2}).format(reading)} °C`)
        : "";
    }
    this.shadowRoot.getElementById("save").disabled = this.saving || !this.drafts.size;
    this.shadowRoot.getElementById("refresh").disabled = this.reading;
    const choices = Object.entries(this.snapshot.sensors);
    const signature = JSON.stringify(choices);
    const select = this.shadowRoot.getElementById("diagnose-sensor");
    if (this.diagnosticChoices !== signature) {
      const previous = select.value;
      const assigned = this.snapshot.circuits.find(row => row.applied && Object.hasOwn(this.snapshot.sensors, row.applied));
      select.replaceChildren(...choices.map(([value, label]) => new Option(label, value)));
      select.value = Object.hasOwn(this.snapshot.sensors, previous) ? previous : (assigned?.applied ?? choices[0]?.[0] ?? "");
      this.diagnosticChoices = signature;
    }
    select.disabled = this.diagnosing || !choices.length;
    this.shadowRoot.getElementById("diagnose").disabled = this.diagnosing || !choices.length;
  }

  notice(message, error = false) {
    const notice = this.shadowRoot.getElementById("notice");
    notice.textContent = message;
    notice.toggleAttribute("data-error", error);
  }

  async save(changes = [...this.drafts.values()]) {
    const opened = this.opened;
    this.saving = true;
    this.notice("");
    this.update();
    try {
      const snapshot = await this.call("save", { changes });
      if (this.opened !== opened) return;
      this.snapshot = snapshot;
      for (const { circuit } of changes) {
        this.drafts.delete(circuit);
        this.readings.delete(circuit);
      }
      this.notice(this.messages.saved);
    } catch (err) {
      if (this.opened === opened) this.notice(err.message || String(err), true);
    } finally {
      if (this.opened === opened) {
        this.saving = false;
        this.update();
      }
    }
  }

  async poll() {
    if (this.saving || this.refreshing) return;
    const opened = this.opened;
    this.refreshing = true;
    try {
      const next = await this.call("info");
      if (this.opened !== opened || this.saving) return;
      const newlyLinked = next.circuits.some(row => !row.pending && row.applied
        && this.snapshot.circuits.some(old => old.circuit === row.circuit && old.pending));
      this.snapshot = next;
      this.update();
      if (newlyLinked || (Date.now() - this.lastRead > 20000 && next.circuits.some(row =>
        row.applied && !row.pending && typeof this.readings.get(row.circuit) !== "number"))) {
        this.readTemperatures(true);
      }
    } catch (err) {
      if (this.opened === opened) this.notice(err.message || String(err), true);
    } finally {
      if (this.opened === opened) this.refreshing = false;
    }
  }

  async readBindings() {
    const opened = this.opened;
    const sensor = this.shadowRoot.getElementById("diagnose-sensor").value;
    const output = this.shadowRoot.getElementById("diagnostic-result");
    const t = this.messages;
    this.diagnosing = true;
    this.update();
    output.textContent = t.checkingBindings;
    let page;
    let total;
    const bindings = [];
    try {
      do {
        page = await this.call("bindings", { sensor, start_index: bindings.length });
        if (this.opened !== opened) return;
        total ??= page.total;
        if (total !== page.total) throw Error(t.bindingsChanged);
        bindings.push(...page.bindings);
        if (page.next_index !== null && page.next_index !== bindings.length) throw Error(t.bindingsChanged);
      } while (page.next_index !== null);

      const temperatureBindings = bindings.filter(row =>
        row.cluster === 0x0402 && row.source_ieee === sensor
        && row.source_endpoint === page.sensor_endpoint && row.address_mode === 3);
      const present = temperatureBindings.filter(row => row.target_ieee === page.h10_ieee)
        .map(row => row.target_endpoint).sort((a, b) => a - b);
      const missing = this.snapshot.circuits.filter(row => row.sensor === sensor && !present.includes(row.circuit))
        .map(row => row.circuit);
      const inHA = temperatureBindings.some(row => row.target_ieee === page.coordinator_ieee);
      output.textContent = [
        `${t.presentBindings}: ${present.join(", ") || "—"}`,
        `${t.missingBindings}: ${missing.join(", ") || "—"}`,
        `${t.coordinatorBinding}: ${inHA ? t.yes : t.no}`,
      ].join("\n");
    } catch (err) {
      if (this.opened === opened) output.textContent = err.message || String(err);
    } finally {
      if (this.opened === opened) {
        this.diagnosing = false;
        this.update();
      }
    }
  }

  async readTemperatures(onlyMissing = false) {
    if (this.reading) return;
    const opened = this.opened;
    this.reading = true;
    this.lastRead = Date.now();
    this.update();
    for (const { circuit, applied, pending } of this.snapshot.circuits) {
      if (this.opened !== opened) return;
      if (!applied || pending || (onlyMissing && typeof this.readings.get(circuit) === "number")) continue;
      let value;
      try {
        value = await this.call("temperature", { circuit });
      } catch {
        value = false;
      }
      if (this.opened === opened && this.snapshot.circuits.some(row =>
        row.circuit === circuit && row.applied === applied && !row.pending)) {
        this.readings.set(circuit, value);
      }
    }
    if (this.opened === opened) {
      this.reading = false;
      this.update();
    }
  }
}

customElements.define(TAG, RoomSensorDialog);

async function openDialog(id) {
  if (opening) return;
  opening = true;
  let root;
  try {
    for (let attempt = 0; attempt < 100; attempt++) {
      root = document.querySelector("home-assistant");
      if (root?.hass?.connection && root.hass.user) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!root?.hass?.user) throw Error(messages.en.openingError);
    const snapshot = await root.hass.callWS({ type: NAMESPACE + "info", device_id: id });
    await customElements.whenDefined("ha-dialog");
    root.dispatchEvent(new CustomEvent("show-dialog", {
      bubbles: true, composed: true,
      detail: { dialogTag: TAG, dialogImport: () => Promise.resolve(), dialogParams: snapshot },
    }));
  } catch (error) {
    root?.dispatchEvent(new CustomEvent("hass-notification", {
      bubbles: true, composed: true, detail: { message: error.message || String(error) },
    }));
  } finally {
    opening = false;
  }
}

// Intercept only the link placed by this integration. The HA device page stays mounted.
document.addEventListener("click", event => {
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  for (const node of event.composedPath()) {
    const href = node.getAttribute?.("href");
    if (!href) continue;
    const target = targetOf(href);
    if (!target) continue;
    event.preventDefault();
    event.stopPropagation();
    openDialog(target.id);
    return;
  }
}, true);

function openLocation() {
  const target = targetOf(location.href);
  if (!target) return;
  target.url.searchParams.delete(PARAMETER);
  history.replaceState(history.state, "", target.url.pathname + target.url.search + target.url.hash);
  openDialog(target.id);
}
window.addEventListener("location-changed", openLocation);
window.addEventListener("popstate", openLocation);
openLocation();
