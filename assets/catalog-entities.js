/* Reviewed exact aliases only. Original labels remain the scientific/source record. */
globalThis.CatalogEntities = {
  map: {organizations:[], systems:[]},
  configure(value) {this.map = value;},
  resolve(sourceLabel, namespace) {
    const literal = String(sourceLabel || '').trim();
    const entry = this.map[namespace].find(row => (row.label === literal || row.aliases.includes(literal)));
    return {id:entry?.id || null, label:entry?.label || literal, sourceLabel:literal,
      kind:entry?.kind || 'unreviewed', key:entry?.id || 'literal:' + literal};
  },
  organization(label) {return this.resolve(String(label || '').split(';')[0].trim(), 'organizations');},
  system(label) {return this.resolve(label, 'systems');}
};
if (typeof module !== 'undefined') module.exports = globalThis.CatalogEntities;
