/* Descriptive name-linked catalog subsets, never model effectiveness estimates. */
const FamilyOutcomes = {
  testContext(record) {
    return !record.evidence?.test_type ? 'Not annotated in this catalog'
      : record.evidence.test_type === 'not reported' ? 'Test context unspecified in annotation' : record.evidence.test_type;
  },
  examples(items, limit = 3) {
    return [...items].sort((a, b) => b.publication_date.localeCompare(a.publication_date) || a.id.localeCompare(b.id)).slice(0, limit);
  },
  summary(items) {
    const groups = key => [...new Set(items.map(key))].sort().map(label => ({label, members:items.filter(s => key(s) === label)}));
    return {fields:groups(s => s.field), tests:groups(s => this.testContext(s)),
      annotations:groups(s => s.evidence ? 'Evidence annotation present' : 'Not annotated in this catalog')};
  },
  select(family, discoveries, field = '', year = '') {
    const ids = new Set(family.discoveries);
    return discoveries.filter(s => ids.has(s.id) && (!field || s.field === field) && (!year || s.publication_date.startsWith(year)));
  }
};
if (typeof module !== 'undefined') module.exports = FamilyOutcomes;
