"""Exercise shared chart events without a browser or third-party DOM dependency."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tagName) {
    this.tagName = tagName; this.dataset = {}; this.children = []; this.listeners = {};
    this.attributes = {}; this.classes = new Set(); this.textContent = ''; this.value = '';
    this.classList = {add:c => this.classes.add(c), remove:c => this.classes.delete(c)};
  }
  append(...nodes) { this.children.push(...nodes); }
  after(...nodes) { this.siblings = nodes; }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, extra = {}) {
    const e = {preventDefault() {this.prevented = true;}, ...extra};
    (this.listeners[type] || []).forEach(fn => fn(e)); return e;
  }
  focus(options) { this.focused = options; }
  getBoundingClientRect() { return {left:20, top:30, width:2}; }
  querySelector(selector) {
    if (selector === '.su') return this.children.find(n => n.classes.has('su'));
    return this.children.find(n => n.dataset.i === selector.match(/data-i="(\d+)"/)[1]);
  }
  querySelectorAll(tagName) { return this.children.filter(n => n.tagName === tagName); }
}
globalThis.document = {createElement:tag => new Element(tag)};
require('./assets/catalog-ui.js');
const ui = globalThis.CatalogUI;
function chart(points, options = {}) {
  const svg = new Element('svg');
  points.forEach((p, i) => {const mark = new Element('line'); mark.dataset.i = String(i); svg.append(mark);});
  svg.scale = 1;
  svg.createSVGPoint = () => ({matrixTransform(matrix) {return {x:this.x * matrix.scale, y:this.y * matrix.scale};}});
  svg.getScreenCTM = () => ({scale:svg.scale, inverse() {return {scale:1 / svg.scale};}});
  const opened = [], tips = [];
  ui.chartInteraction(svg, points, {describe:p => [p.title, p.date || 'Date', 'Editorial relevance 60'],
    open:p => opened.push(p), showTip:(...args) => tips.push(args), hideTip() {}, ...options});
  const [status, chooser] = svg.siblings, [label, button] = chooser.children, [caption, select] = label.children;
  return {svg, status, chooser, select, button, opened, tips, caption};
}
'''


class ChartInteractionTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run(['node', '-e', HARNESS + code], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_same_date_tap_exposes_all_records_without_a_hover_or_date_jitter(self):
        self.run_js(r'''
const points = [{x:20, date:'2025-01-01', title:'First'}, {x:20, date:'2025-01-01', title:'Second'},
 {x:70, date:'2025-02-01', title:'Other'}];
const c = chart(points);
c.svg.fire('click', {clientX:20, clientY:10});
assert.equal(c.opened.length, 0, 'A tied date must ask which entry to open');
assert.equal(c.chooser.hidden, false);
assert.deepEqual(c.select.children.map(n => [n.value, n.textContent]), [[0, 'First'], [1, 'Second']]);
assert.ok(c.select.focused.preventScroll);
c.svg.fire('blur'); c.svg.fire('pointerleave');
c.select.value = '1'; c.select.fire('change'); c.button.fire('click');
assert.deepEqual(c.opened, [points[1]], 'Every same-date record must be reachable by the chooser');
assert.ok(c.status.textContent.includes('Second'));
assert.ok(c.status.textContent.includes('Editorial relevance 60'));
assert.equal(points[0].x, points[1].x, 'Dates must remain at the same true position');
c.chooser.fire('keydown', {key:'Escape'});
assert.equal(c.chooser.hidden, true); assert.ok(c.svg.focused.preventScroll);
c.svg.fire('click', {clientX:70, clientY:10});
assert.deepEqual(c.opened, [points[1], points[2]], 'A fresh unique tap must open its own entry');
c.svg.fire('click', {clientX:200, clientY:10}); assert.equal(c.opened.length, 2);
''')

    def test_nearby_dates_use_css_pixel_distance_and_keep_the_nearest_selected(self):
        self.run_js(r'''
const points = [{x:20,date:'2025-01-01',title:'Nearest'}, {x:20,date:'2025-01-01',title:'Same date'},
 {x:32,date:'2025-01-02',title:'Nearby'}, {x:38,date:'2025-01-03',title:'Too far'}];
const c = chart(points); c.svg.scale = 0.5;
c.svg.fire('click', {clientX:10,clientY:10});
assert.equal(c.opened.length, 0);
assert.equal(c.chooser.hidden, false);
assert.equal(c.select.value, '0', 'The nearest mark remains selected');
assert.deepEqual(c.select.children.map(n => n.value), [0, 1, 2], 'Include marks within 8 CSS pixels and every same-date entry');
assert.deepEqual(c.select.children.map(n => n.textContent), ['Nearest — 2025-01-01', 'Same date — 2025-01-01', 'Nearby — 2025-01-02']);
assert.ok(c.caption.textContent.includes('nearby entries'));
c.select.value = '2'; c.button.fire('click'); assert.deepEqual(c.opened, [points[2]]);
assert.deepEqual(points.map(p => p.x), [20, 20, 32, 38], 'The chooser must not jitter any date');
''')

    def test_keyboard_visits_ties_in_date_order_and_announces_selection(self):
        self.run_js(r'''
const points = [{x:70, title:'Last'}, {x:20, title:'First'}, {x:20, title:'Tied'}];
const c = chart(points);
assert.equal(c.status.attributes.role, 'status'); assert.equal(c.status.attributes['aria-atomic'], 'true');
assert.equal(c.svg.fire('keydown', {key:'ArrowRight'}).prevented, true);
assert.ok(c.status.textContent.startsWith('1 of 3. First.'));
c.svg.fire('keydown', {key:'ArrowRight'}); c.svg.fire('keydown', {key:'Enter'});
assert.deepEqual(c.opened, [points[2]]);
c.svg.fire('keydown', {key:'End'}); assert.ok(c.status.textContent.includes('Last'));
c.svg.fire('keydown', {key:'ArrowRight'}); c.svg.fire('keydown', {key:' '});
assert.deepEqual(c.opened, [points[2], points[0]], 'End of chart must clamp safely');
c.svg.fire('keydown', {key:'Escape'}); assert.equal(c.status.textContent, '');
c.svg.fire('keydown', {key:'Enter'}); assert.equal(c.opened.length, 2);
c.svg.fire('keydown', {key:'ArrowLeft'}); assert.ok(c.status.textContent.includes('Last'));
c.svg.fire('keydown', {key:'Home'}); assert.ok(c.status.textContent.includes('First'));
chart([]).svg.fire('keydown', {key:'ArrowRight'});
''')

    def test_scatter_tap_uses_both_axes_and_retains_filter_penalty(self):
        self.run_js(r'''
const points = [{x:20,y:15,title:'Upper'}, {x:20,y:80,title:'Lower'}, {x:25,y:80,title:'Filtered'}];
const c = chart(points, {penalty:p => p.title === 'Filtered' ? 12 : 0, radius:28});
c.svg.fire('click', {clientX:24,clientY:80});
assert.equal(c.select.value, '1', 'Scatter selection must use vertical position and filter penalty');
assert.deepEqual(c.select.children.map(n => n.value), [1, 2], 'Nearby scatter points must also remain selectable');
c.button.fire('click');
assert.deepEqual(c.opened, [points[1]], 'Scatter selection must use vertical position and filter penalty');
c.svg.fire('keydown', {key:'End'}); c.svg.fire('keydown', {key:'Enter'});
assert.deepEqual(c.opened, [points[1], points[2]], 'Dimmed points remain available from the keyboard');
const coincident = chart([{x:20,y:20,date:'2025-01-01',title:'One'}, {x:20,y:20,date:'2025-01-01',title:'Two'},
 {x:20,y:80,date:'2025-01-01',title:'Distant compute'}]);
coincident.svg.fire('click', {clientX:20,clientY:20});
assert.deepEqual(coincident.select.children.map(n => n.value), [0, 1], 'Same-date scatter marks with distant compute must stay separate');
coincident.select.value = '1'; coincident.button.fire('click'); assert.equal(coincident.opened[0].title, 'Two');
''')

    def test_focus_restoration_distinguishes_year_overlay_from_keyboard_control(self):
        self.run_js(r'''
const root = new Element('div');
for (const tag of ['rect', 'circle', 'circle']) {
  const n = new Element(tag); n.dataset = {k:'anno', v:root.children.length === 2 ? '2024' : '2025'}; root.append(n);
}
const old = new Element('circle'); old.dataset = {k:'anno',v:'2025'};
ui.restoreChartFocus(root, old);
assert.equal(root.children[0].focused, undefined);
assert.ok(root.children[1].focused.preventScroll);
assert.equal(root.children[2].focused, undefined);
const cell = new Element('button'); cell.dataset = {field:'biology',year:'2025'}; root.append(cell);
const stale = new Element('button'); stale.dataset = {...cell.dataset}; ui.restoreChartFocus(root, stale);
assert.ok(cell.focused.preventScroll, 'Heatmap controls must match both field and year');
''')
