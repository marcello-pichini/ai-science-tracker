import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('vg', Path(__file__).resolve().parents[1] / 'scripts/build_vuln_global.py')
vg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vg)


def cve(cid, state='PUBLISHED', score=None, vendor='Acme', product='Server'):
    cna = {'descriptions': [{'lang': 'en', 'value': f'{cid} desc'}],
           'affected': [{'vendor': vendor, 'product': product,
                         'versions': [{'version': '1.0', 'lessThan': '1.4', 'status': 'affected', 'versionType': 'semver'}]}]}
    if score is not None:
        cna['metrics'] = [{'cvssV3_1': {'version': '3.1', 'baseScore': score, 'vectorString': 'CVSS:3.1/AV:N'}}]
    if state == 'REJECTED':
        cna = {'rejectedReasons': [{'lang': 'en', 'value': 'duplicate'}]}
    return {'cveMetadata': {'cveId': cid, 'state': state, 'assignerShortName': 'acme',
                            'datePublished': '2025-03-01T00:00:00Z'}, 'containers': {'cna': cna}}


def osv(oid, aliases=(), upstream=(), pkg='lib', **kw):
    return {'id': oid, 'aliases': list(aliases), 'upstream': list(upstream), 'summary': f'{oid} summary',
            'affected': [{'package': {'ecosystem': 'PyPI', 'name': pkg},
                          'ranges': [{'type': 'ECOSYSTEM', 'events': [{'introduced': '0'}, {'fixed': '2.0'}]}]}], **kw}


class GlobalVulnerabilityBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cves = [cve('CVE-2025-0001', score=9.8), cve('CVE-2025-0002', score=5.0), cve('CVE-2025-0003'),
                cve('CVE-2025-0004', state='REJECTED'), cve('CVE-2025-0001', score=9.8)]
        osvs = [
            osv('GHSA-aaaa-bbbb-cccc', aliases=['CVE-2025-0001'], database_specific={'severity': 'CRITICAL'}),
            osv('PYSEC-2025-1', aliases=['GHSA-dddd-eeee-ffff'],
                severity=[{'type': 'CVSS_V3', 'score': 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'}]),  # non-CVE pair -> one row
            osv('GHSA-dddd-eeee-ffff', aliases=['PYSEC-2025-1']),
            osv('GHSA-two-cves', aliases=['CVE-2025-0001', 'CVE-2025-0002']),  # attaches to both, merges nothing
            osv('RHSA-2025:1', upstream=['CVE-2025-0001', 'CVE-2025-0002']),
            osv('UBUNTU-CVE-2025-0003', upstream=['CVE-2025-0003']),  # reference only
            osv('CGA-xxxx', aliases=['CVE-2025-0003']),  # dropped
            osv('MAL-2025-9', pkg='evil'),
            osv('PYSEC-2025-7', aliases=['GHSA-aaaa-bbbb-cccc']),  # no CVE itself, joins CVE-2025-0001 via GHSA
            osv('GSD-2021-1', pkg='Kernel'),  # unverified automated ID without CVE: dropped
            osv('JLSEC-2025-1', upstream=['CVE-2025-0003'], pkg='Foo_jll'),  # downstream package of a CVE
            osv('GHSA-gone', aliases=['CVE-2025-0003'], withdrawn='2025-05-01'),
        ]
        extra = {'nvd': {'CVE-2025-0002': {'cvss': [{'source': 'NVD', 'version': '3.1', 'score': 7.5, 'vector': None}],
                                           'cpe': [{'criteria': 'cpe:2.3:a:acme:server:*', 'versionEndExcluding': '1.4'}],
                                           'status': 'Analyzed'}},
                 'kev': {'CVE-2025-0001': {'date_added': '2025-04-01', 'ransomware': 'Unknown'},
                         'CVE-2025-0099': {'date_added': '2025-05-01', 'ransomware': 'Unknown'}},
                 'epss': {'CVE-2025-0001': {'score': 0.9, 'percentile': 0.99, 'date': '2025-11-26'}},
                 'euvd': {'CVE-2025-0001': {'id': 'EUVD-2025-1', 'exploited_since': None, 'url': 'u'}}}
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.report = vg.build(cves, osvs, extra, out)
        with gzip.open(out / 'vulnerabilities_global.jsonl.gz', 'rt') as f:
            cls.rows = {r['id']: r for r in map(json.loads, f)}
        with gzip.open(out / 'malicious_packages.jsonl.gz', 'rt') as f:
            cls.mal = [json.loads(line) for line in f]
        with gzip.open(out / 'products.json.gz', 'rt') as f:
            cls.products = {p['product_key']: p for p in json.load(f)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_one_row_per_cve_and_rejected_kept_flagged(self):
        self.assertEqual(self.report['duplicate_cve_files'], 1)
        self.assertEqual(self.rows['CVE-2025-0004']['state'], 'REJECTED')
        self.assertEqual(self.report['cve_states'], {'PUBLISHED': 3, 'REJECTED': 1})

    def test_aliases_attach_without_merging_cves(self):
        a, b = self.rows['CVE-2025-0001'], self.rows['CVE-2025-0002']
        self.assertIn('GHSA-two-cves', a['aliases'])
        self.assertIn('GHSA-two-cves', b['aliases'])
        self.assertEqual(a['aliases'], ['EUVD-2025-1', 'GHSA-aaaa-bbbb-cccc', 'GHSA-two-cves', 'PYSEC-2025-7'])
        self.assertNotIn('PYSEC-2025-7', self.rows)

    def test_distro_advisories_attach_to_each_cve(self):
        for cid in ('CVE-2025-0001', 'CVE-2025-0002'):
            self.assertEqual([x['id'] for x in self.rows[cid]['advisories']], ['RHSA-2025:1'])
        ref = self.rows['CVE-2025-0003']['advisories'][-1]
        self.assertEqual(ref, {'id': 'UBUNTU-CVE-2025-0003', 'source': None, 'license': None,
                               'url': 'https://osv.dev/vulnerability/UBUNTU-CVE-2025-0003'})
        c3 = self.rows['CVE-2025-0003']
        self.assertEqual([p['package'] for p in c3['packages']], ['Foo_jll'], 'only the licensed downstream package')
        self.assertEqual([x['id'] for x in c3['advisories']], ['JLSEC-2025-1', 'UBUNTU-CVE-2025-0003'])
        self.assertNotIn('GSD-2021-1', self.rows)
        self.assertFalse(any(p['source'].startswith('RHSA') for p in self.rows['CVE-2025-0002']['packages']))

    def test_non_cve_aliases_form_one_row(self):
        self.assertIn('GHSA-dddd-eeee-ffff', self.rows)
        self.assertEqual(self.rows['GHSA-dddd-eeee-ffff']['aliases'], ['PYSEC-2025-1'])
        self.assertNotIn('PYSEC-2025-1', self.rows)

    def test_rows_share_one_schema(self):
        self.assertEqual({frozenset(r) for r in self.rows.values()}, {frozenset(vg.BLANK)})
        self.assertEqual(self.rows['GHSA-dddd-eeee-ffff']['cvss'][0]['version'], '3.1')

    def test_malicious_packages_and_withdrawn_kept_out(self):
        self.assertEqual([m['id'] for m in self.mal], ['MAL-2025-9'])
        self.assertNotIn('MAL-2025-9', self.rows)
        self.assertFalse(any('GHSA-gone' in r['aliases'] for r in self.rows.values()))
        self.assertNotIn('CGA-xxxx', json.dumps(self.rows))

    def test_scores_stay_attributed_and_flags_join(self):
        b = self.rows['CVE-2025-0002']
        self.assertEqual([(c['source'], c['score']) for c in b['cvss']], [('acme', 5.0), ('NVD', 7.5)])
        a = self.rows['CVE-2025-0001']
        self.assertEqual(a['kev']['date_added'], '2025-04-01')
        self.assertEqual(a['epss']['score'], 0.9)
        self.assertEqual(a['euvd']['id'], 'EUVD-2025-1')

    def test_kev_cve_missing_from_snapshot_stays_findable(self):
        r = self.rows['CVE-2025-0099']
        self.assertEqual((r['state'], r['kev']['date_added']), ('NOT_IN_CVE_LIST_SNAPSHOT', '2025-05-01'))

    def test_product_family_collapses_editions_only(self):
        self.assertEqual(vg.family('microsoft:windows server 2019 (server core installation)'), 'microsoft:windows server')
        self.assertEqual(vg.family('linux:linux'), 'linux:kernel')
        self.assertEqual(vg.family('7-zip:7-zip'), '7-zip:7-zip')
        self.assertEqual(vg.family('mozilla:firefox esr'), 'mozilla:firefox')  # curated map: ESR is a Firefox branch
        self.assertEqual(vg.family('redhat:enterprise linux 8.4 advanced mission critical update support'), 'red hat:enterprise linux')
        self.assertEqual(vg.family('apple:iphone os'), 'apple:ios and ipados')
        self.assertEqual(vg.CATEGORY[vg.family('apache software foundation:apache http server')], 'web server')
        for raw in ('microsoft:windows 10 version 1903 for x64-based systems', 'microsoft:windows 11 version 24h2'):
            self.assertEqual(vg.family(raw), 'microsoft:windows')
        for raw in ('microsoft:windows server 2008 r2 service pack 1', 'microsoft:windows server 2022, 23h2 edition',
                    'microsoft:windows server,'):
            self.assertEqual(vg.family(raw), 'microsoft:windows server')
        for raw in ('google inc.:android', ':android', 'google:android 14'):
            self.assertEqual(vg.family(raw), 'google:android')
        self.assertEqual(vg.family('qualcomm, inc.:snapdragon'), 'qualcomm:snapdragon')
        self.assertEqual(vg.family('big-ip:big-ip (ltm, asm)'), 'big-ip:big-ip')
        self.assertEqual(vg.family('cups easy:cups easy (purchase & inventory)'), 'cups easy:cups easy')
        self.assertEqual(vg.family('apache software foundation:apache http server'), 'apache:http server')
        self.assertEqual(vg.family('the postgresql global development group:postgresql'), 'postgresql:postgresql')

    def test_curated_map_is_consistent(self):
        keys = [k for ks in vg.PRODUCT_MAP['categories'].values() for k in ks]
        self.assertEqual(len(keys), len(set(keys)), 'a product sits in one category')
        self.assertEqual([k for k in keys if vg.canonical(k) != k], [], 'categories use canonical keys')
        self.assertEqual([v for v in vg.PRODUCT_MAP['aliases'].values() if vg.canonical(v) != v], [])
        self.assertEqual(vg.category_of('qualcomm:wcd9380 firmware'), 'chipset firmware')
        self.assertEqual(vg.category_of('netgear:r7800 firmware'), 'router and network device firmware')
        self.assertEqual(vg.category_of('siemens:simatic s7-1500 cpu 1518-4 pn/dp mfp'), 'industrial control and OT system')
        self.assertEqual(vg.category_of('acme:widget firmware'), 'device firmware')
        self.assertIsNone(vg.category_of('acme:widget'))

    def test_cvss_base_score_from_vector(self):
        cases = {'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H': 9.8, 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H': 10.0,
                 'CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N': 5.5, 'CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N': 6.1,
                 'CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N': 0.0, 'AV:N/AC:L/Au:N/C:P/I:P/A:P': 7.5,
                 'AV:N/AC:M/Au:N/C:N/I:P/A:N': 4.3, 'CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N': 9.3,
                 # v4 values below are the majority score CNAs publish for the same vector
                 'CVSS:4.0/AV:L/AC:L/AT:N/PR:L/UI:N/VC:N/VI:N/VA:L/SC:N/SI:N/SA:N': 4.8,
                 'CVSS:4.0/AV:N/AC:L/AT:N/PR:H/UI:N/VC:N/VI:N/VA:N/SC:L/SI:N/SA:N': 5.1,
                 'CVSS:4.0/AV:L/AC:L/AT:P/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N': 5.7,
                 'CVSS:4.0/AV:N/AC:L/AT:P/PR:N/UI:N/VC:N/VI:H/VA:L/SC:N/SI:N/SA:N': 8.3,
                 'CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N': 0.0,
                 'CVSS:4.0/AV:N/AC:L': None,
                 'garbage': None}
        self.assertEqual({v: vg.cvss_base(v) for v in cases}, cases)
        self.assertTrue(self.rows['GHSA-dddd-eeee-ffff']['cvss'][0]['score_computed'])

    def test_lifecycle_matches_cpe_and_purl_identifiers(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'full.json'
            path.write_text(json.dumps({'result': [{'name': 'nginx', 'label': 'nginx', 'links': {'html': 'https://e/nginx'},
                'identifiers': [{'type': 'cpe', 'id': 'cpe:/a:nginx:nginx'}, {'type': 'purl', 'id': 'pkg:npm/%40angular/core'},
                                {'type': 'purl', 'id': 'pkg:maven/org.apache.struts/struts2-core'}],
                'releases': [{'name': '1.26', 'isEol': False, 'isMaintained': True, 'latest': {'name': '1.26.2'}}]}]}))
            life = vg.load_eol(path)
        self.assertEqual(sorted(life), ['f5:nginx', 'maven:org.apache.struts:struts2-core', 'npm:@angular/core'])
        self.assertEqual(life['f5:nginx']['releases'][0]['latest'], '1.26.2')

    def test_legacy_cve_product_comes_from_nvd_cpe(self):
        row = {**vg.BLANK, 'affected': [{'vendor': 'n/a', 'product': 'n/a'}],
               'nvd_cpe': [{'criteria': 'cpe:2.3:a:apache:http_server:2.4.1:*:*:*:*:*:*:*'}]}
        self.assertEqual([p['product_key'] for p in vg.row_products(row)], ['apache:http server'])

    def test_product_counts_use_highest_attributed_score(self):
        p = self.products['acme:server']
        self.assertEqual(p['total'], 3)
        self.assertEqual(p['kev'], 1)
        self.assertEqual(p['by_severity'], {'critical': 1, 'high': 1, 'unscored': 1})


class EnrichmentTests(unittest.TestCase):
    """Each row links every product, weakness, attack pattern, reference and public exploit its sources name."""

    @classmethod
    def setUpClass(cls):
        rec = cve('CVE-2025-0010', score=9.8, vendor='Apache Software Foundation', product='Apache HTTP Server')
        cna = rec['containers']['cna']
        cna['problemTypes'] = [{'descriptions': [{'cweId': 'CWE-79', 'lang': 'en'}, {'description': 'n/a'}]}]
        cna['impacts'] = [{'capecId': 'CAPEC-1'}]
        cna['references'] = [{'url': 'https://a/patch', 'tags': ['patch']}]
        rec['containers']['adp'] = [{'providerMetadata': {'shortName': 'CISA-ADP'},
                                     'affected': [{'vendor': 'apache', 'product': 'http_server',
                                                   'cpes': ['cpe:2.3:a:apache:http_server:*:*:*:*:*:*:*:*'],
                                                   'versions': [{'version': '0', 'lessThan': '2.4.60', 'status': 'affected'}]}],
                                     'problemTypes': [{'descriptions': [{'cweId': 'CWE-20'}]}],
                                     'references': [{'url': 'https://a/patch', 'tags': ['x_transferred']}]}]
        osvs = [osv('GHSA-enri-ched-0001', aliases=['CVE-2025-0010'], pkg='httpd-lib',
                    database_specific={'cwe_ids': ['CWE-79', 'CWE-116']})]
        extra = {'nvd': {'CVE-2025-0010': {'cvss': [], 'cpe': [{'criteria': 'cpe:2.3:a:apache:http_server:*:*:*:*:*:*:*:*',
                                                                'versionEndExcluding': '2.4.61'}],
                                           'status': 'Analyzed', 'cwe': ['CWE-20'],
                                           'references': [{'url': 'https://a/exploit', 'tags': ['Exploit']}]}},
                 'kev': {}, 'epss': {}, 'euvd': {},
                 'cwe': {'CWE-79': {'name': 'XSS', 'capec': ['CAPEC-63', 'CAPEC-1']}, 'CWE-20': {'name': 'Input', 'capec': []}},
                 'capec': {'CAPEC-1': 'ACL', 'CAPEC-63': 'Script'},
                 'exploits': {'CVE-2025-0010': {'items': [{'source': 'Metasploit', 'id': 'exploit/x'}],
                                                'counts': {'metasploit': 1, 'poc_github': 3}}}}
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        vg.build([rec], osvs, extra, out)
        with gzip.open(out / 'vulnerabilities_global.jsonl.gz', 'rt') as f:
            cls.row = json.loads(f.readline())
        with gzip.open(out / 'products.json.gz', 'rt') as f:
            cls.products = {p['product_key']: p for p in json.load(f)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_weaknesses_from_every_container_with_names(self):
        self.assertEqual(self.row['cwe'], [{'id': 'CWE-20', 'name': 'Input'}, {'id': 'CWE-79', 'name': 'XSS'},
                                           {'id': 'CWE-116', 'name': None}])
        self.assertEqual(self.row['capec'], [{'id': 'CAPEC-1', 'name': 'ACL', 'via': 'CNA'},
                                             {'id': 'CAPEC-63', 'name': 'Script', 'via': 'CWE-79'}])

    def test_products_merge_cna_adp_nvd_and_packages(self):
        prods = {p['product_key']: p for p in self.row['products']}
        self.assertEqual(sorted(prods), ['apache:http server', 'pypi:httpd-lib'])
        httpd = prods['apache:http server']
        self.assertEqual(httpd['sources'], ['CISA-ADP', 'NVD', 'acme'])
        self.assertEqual(httpd['cpe'], ['cpe:2.3:a:apache:http_server'])
        self.assertEqual(httpd['fixed'], ['1.4', '2.4.60', '2.4.61'])
        self.assertEqual(prods['pypi:httpd-lib']['fixed'], ['2.0'])
        self.assertEqual((httpd['types'], prods['pypi:httpd-lib']['types']), (['application'], ['package']))

    def test_references_merged_once_with_tags(self):
        self.assertEqual(self.row['references'], [
            {'url': 'https://a/patch', 'tags': ['patch', 'x_transferred'], 'sources': ['acme', 'CISA-ADP']},
            {'url': 'https://a/exploit', 'tags': ['Exploit'], 'sources': ['NVD']}])

    def test_exploits_and_summary(self):
        self.assertEqual(self.row['exploits'], [{'source': 'Metasploit', 'id': 'exploit/x'}])
        s = self.row['exploit_summary']
        self.assertEqual((s['metasploit'], s['poc_github'], s['exploitdb'], s['public_exploit'], s['kev']),
                         (1, 3, 0, True, False))
        self.assertEqual(self.products['apache:http server']['public_exploit'], 1)
        with gzip.open(Path(self.tmp.name) / 'categories.json.gz', 'rt') as f:
            web = json.load(f)['web server']
        self.assertEqual([(p['product_key'], p['total']) for p in web], [('apache:http server', 1)])

    def test_exploit_loader_reads_each_source(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d)
            (src / 'exploitdb').mkdir()
            (src / 'exploitdb/files_exploits.csv').write_text(
                'id,file,description,date_published,type,platform,verified,codes\n'
                '1,x,"t",2020-01-01,remote,linux,1,CVE-2020-0001;OSVDB-1\n2,y,"u",2020-01-02,dos,win,0,\n')
            (src / 'pocgithub/repo/2020').mkdir(parents=True)
            repos = [{'full_name': f'u/r{i}', 'html_url': f'https://github.com/u/r{i}', 'stargazers_count': i,
                      'created_at': '2020-02-02T00:00:00Z', 'fork': i == 0} for i in range(13)]
            (src / 'pocgithub/repo/2020/CVE-2020-0001.json').write_text(json.dumps(repos))
            out, stats = vg.load_exploits(src)
        hit = out['CVE-2020-0001']
        self.assertEqual(hit['counts'], {'exploitdb': 1, 'poc_github': 12})
        self.assertEqual([x['id'] for x in hit['items']][:3], ['EDB-1', 'u/r12', 'u/r11'])
        self.assertEqual(len(hit['items']), 1 + vg.POC_KEEP)
        self.assertEqual((stats['exploitdb'], stats['exploitdb_with_cve']), (2, 1))


class OtherDatabaseTests(unittest.TestCase):
    """National databases, CERT/CSAF advisories, GCVE and sightings from the CIRCL dumps."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)

        def dump(name, recs):
            (d / f'{name}.ndjson').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs))

        dump('cnvd', [{'number': 'CNVD-2020-1', 'cves': {'cve': {'cveNumber': 'CVE-2020-0001'}}, 'openTime': '2020-01-02'},
                      {'number': 'CNVD-2020-2', 'cves': {'cve': [{'cveNumber': 'CVE-2020-0002'}, {'cveNumber': 'CVE-2020-0003'}]}},
                      {'number': 'CNVD-2020-3', 'openTime': '2020-03-01'},  # no CVE; grouped with VAR below
                      {'number': 'CNVD-2020-4', 'openTime': '2020-04-01'},  # no CVE; cited by a VAR that has one
                      {'number': 'CNVD-2020-5', 'isEvent': '事件型漏洞'}])
        dump('variot', [{'id': 'VAR-202003-1', 'external_ids': {'data': [{'db': 'CNVD', 'id': 'CNVD-2020-3'}]},
                         'sources_release_date': {'data': [{'date': '2020-02-28T00:00:00'}]}},
                        {'id': 'VAR-202004-1', 'external_ids': {'data': [{'db': 'CNVD', 'id': 'CNVD-2020-4'},
                                                                          {'db': 'NVD', 'id': 'CVE-2020-0004'}]}}])
        dump('fstec', [{'Идентификатор': 'BDU:2020-00001', 'Дата публикации': '05.03.2020',
                        'Идентификаторы других систем описаний уязвимости': 'CVE-2020-0001, OSVDB ID:1'}])
        dump('certfr_avis', [{'reference': 'CERTFR-2020-AVI-1', 'cves': [{'name': 'CVE-2020-0001'}]}])
        dump('csaf_acme', [{'document': {'tracking': {'id': 'ACME-1'}, 'publisher': {'name': 'Acme'},
                                         'references': [{'category': 'self', 'url': 'https://acme/1'}]},
                            'vulnerabilities': [{'cve': 'CVE-2020-0002'}]}])
        dump('gna-1', [{'cveMetadata': {'cveId': 'CVE-2020-0001', 'vulnId': 'gcve-1-2020-0001'}},
                       {'cveMetadata': {'vulnId': 'GCVE-1-2020-0002', 'datePublished': '2020-05-01'},
                        'containers': {'cna': {'title': 'T', 'descriptions': [{'lang': 'en', 'value': 'D'}]}}}])
        dump('gna-1988', [{'cveMetadata': {'vulnId': 'GCVE-1988-2020-1'},
                           'containers': {'cna': {'descriptions': [{'lang': 'en', 'value': 'not copied'}]}}}])
        dump('sightings', [{'vulnerability': 'cve-2020-0001', 'type': 'exploited', 'creation_timestamp': '2021-01-02T00:00:00Z'},
                           {'vulnerability': 'CVE-2020-0001', 'type': 'seen', 'creation_timestamp': '2020-12-01T00:00:00Z'}])
        cls.o = vg.load_other_dbs(d)
        cls.rows = {r['id']: r for r in cls.o['rows']}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_records_citing_cves_become_references_of_those_cves_only(self):
        refs = self.o['refs']
        self.assertEqual(sorted(refs['CVE-2020-0001']), ['BDU:2020-00001', 'CERTFR-2020-AVI-1', 'CNVD-2020-1'])
        self.assertEqual(sorted(refs['CVE-2020-0002']), ['ACME-1', 'CNVD-2020-2'])
        self.assertEqual(sorted(refs['CVE-2020-0004']), ['CNVD-2020-4', 'VAR-202004-1'], 'one hop through VARIoT')
        self.assertEqual(refs['CVE-2020-0001']['CERTFR-2020-AVI-1']['license'], 'Licence-Ouverte-2.0')
        self.assertEqual(refs['CVE-2020-0001']['BDU:2020-00001']['url'], 'https://bdu.fstec.ru/vul/2020-00001')

    def test_records_without_cve_become_grouped_reference_rows(self):
        r = self.rows['VAR-202003-1']
        self.assertEqual((r['aliases'], r['published'], r['description']), (['CNVD-2020-3'], '2020-02-28', ''))
        self.assertNotIn('CNVD-2020-3', self.rows)
        self.assertNotIn('CNVD-2020-5', self.rows)
        self.assertNotIn('CNVD-2020-4', self.rows)

    def test_gcve_content_only_from_gna_1(self):
        self.assertEqual(self.o['aliases']['CVE-2020-0001'], {'GCVE-1-2020-0001'})
        self.assertEqual((self.rows['GCVE-1-2020-0002']['title'], self.rows['GCVE-1-2020-0002']['description']), ('T', 'D'))
        other = self.rows['GCVE-1988-2020-1']
        self.assertEqual((other['description'], other['advisories'][0]['license']), ('', vg.REFERENCE_ONLY))
        self.assertEqual({frozenset(r) for r in self.rows.values()}, {frozenset(vg.BLANK)})

    def test_sightings_are_counts_only(self):
        self.assertEqual(self.o['sightings']['CVE-2020-0001'],
                         {'counts': {'exploited': 1, 'seen': 1}, 'first': '2020-12-01', 'last': '2021-01-02',
                          'source': 'CIRCL Vulnerability-Lookup sightings'})


class TriageFieldTests(unittest.TestCase):
    """Fix information, SSVC, exposure, class, priority, version ranges and the vendor/CWE aggregates."""

    def test_euvd_date_is_iso(self):
        self.assertEqual(vg.euvd_date('Dec 10, 2021, 12:00:00 AM'), '2021-12-10')
        self.assertEqual(vg.euvd_date('2021-12-10'), '2021-12-10')

    @classmethod
    def setUpClass(cls):
        rec = cve('CVE-2025-0020', vendor='Acme', product='Gateway')
        cna = rec['containers']['cna']
        cna['metrics'] = [{'cvssV3_1': {'version': '3.1', 'baseScore': 9.8,
                                        'vectorString': 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'}}]
        cna['problemTypes'] = [{'descriptions': [{'cweId': 'CWE-121'}, {'cweId': 'CWE-9999'}]}]
        cna['solutions'] = [{'lang': 'en', 'value': 'Upgrade   to 1.4.'}]
        cna['credits'] = [{'lang': 'en', 'type': 'finder', 'value': 'A. Researcher'}]
        cna['references'] = [{'url': 'https://acme/patch', 'tags': ['patch']},
                             {'url': 'https://acme/adv', 'tags': ['vendor-advisory']},
                             {'url': 'https://github.com/acme/gateway/pull/7/commits/abcdef1234567890', 'tags': []}]
        rec['cveMetadata']['dateReserved'] = '2025-01-01T00:00:00Z'
        cna['affected'][0]['versions'].append({'version': '1.3.9', 'status': 'unaffected'})
        rec['containers']['adp'] = [{'providerMetadata': {'shortName': 'CISA-ADP'}, 'metrics': [{'other': {
            'type': 'ssvc', 'content': {'timestamp': '2025-03-02T00:00:00Z', 'options': [
                {'Exploitation': 'poc'}, {'Automatable': 'yes'}, {'Technical Impact': 'total'}]}}}]}]
        low = cve('CVE-2025-0021', vendor='Acme', product='Gateway')
        low['containers']['cna']['metrics'] = [{'cvssV2_0': {'version': '2.0', 'baseScore': 2.1,
                                                             'vectorString': 'AV:L/AC:L/Au:S/C:P/I:N/A:N'}}]
        extra = {'nvd': {'CVE-2025-0020': {'cvss': [{'source': 'NVD', 'version': '3.1', 'score': 7.5,
                                                     'vector': 'CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:H/I:N/A:N'}],
                                           'cpe': [{'criteria': 'cpe:2.3:h:acme:gateway:2.0:*:*:*:*:*:*:*'}]}},
                 'kev': {'CVE-2025-0020': {'date_added': '2025-04-01', 'due_date': '2025-04-22',
                                           'required_action': 'Apply updates.'}},
                 'epss': {}, 'euvd': {},
                 'cwe': {'CWE-9999': {'name': 'Child', 'capec': [], 'parents': ['CWE-787']},
                         'CWE-121': {'name': 'Stack', 'capec': ['CAPEC-100'], 'parents': [], 'top25': True,
                                     'owasp': ['A03:2021 Injection']}},
                 'capec': {'CAPEC-100': 'Overflow Buffers'},
                 'capec_attack': {'CAPEC-100': [{'id': 'T1499', 'name': 'Endpoint Denial of Service'}]}}
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        vg.build([rec, low], [], extra, out)
        with gzip.open(out / 'vulnerabilities_global.jsonl.gz', 'rt') as f:
            cls.rows = {r['id']: r for r in map(json.loads, f)}
        cls.row = cls.rows['CVE-2025-0020']
        with gzip.open(out / 'vendors.json.gz', 'rt') as f:
            cls.vendors = {v['vendor']: v for v in json.load(f)}
        with gzip.open(out / 'weaknesses.json.gz', 'rt') as f:
            cls.weak = {w['cwe_id']: w for w in json.load(f)}
        with gzip.open(out / 'product_versions.jsonl.gz', 'rt') as f:
            cls.index = [json.loads(line) for line in f]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_primary_score_prefers_cna_and_exposure_reads_its_vector(self):
        self.assertEqual(self.row['severity'], {'score': 9.8, 'band': 'critical', 'version': '3.1', 'source': 'acme',
                                                'max_score': 9.8})
        e = self.row['exposure']
        self.assertEqual((e['attack_vector'], e['privileges_required'], e['user_interaction'], e['remote_unauthenticated']),
                         ('network', 'none', 'none', True))
        e2 = self.rows['CVE-2025-0021']['exposure']
        self.assertEqual((e2['attack_vector'], e2['privileges_required'], e2['remote_unauthenticated']), ('local', 'low', False))

    def test_ssvc_class_and_priority(self):
        self.assertEqual({k: self.row['ssvc'][k] for k in ('exploitation', 'automatable', 'technical_impact', 'date')},
                         {'exploitation': 'poc', 'automatable': 'yes', 'technical_impact': 'total', 'date': '2025-03-02'})
        self.assertEqual(self.row['vuln_class'], ['memory corruption'])  # CWE-9999 inherits CWE-787
        self.assertEqual((self.row['cwe_top25'], self.row['owasp_top10']), (True, ['A03:2021 Injection']))
        self.assertEqual(self.row['priority']['level'], 'act now')
        self.assertIn('CISA KEV', self.row['priority']['reasons'])
        self.assertEqual(self.rows['CVE-2025-0021']['priority']['level'], 'low')

    def test_remediation_credits_and_timeline(self):
        rem = self.row['remediation']
        self.assertEqual(rem['solutions'], ['Upgrade to 1.4.'])
        self.assertEqual((rem['patch_urls'], rem['vendor_advisory_urls']), (['https://acme/patch'], ['https://acme/adv']))
        self.assertEqual(rem['fixed_versions'], {'acme:gateway': ['1.3.9', '1.4']})
        self.assertEqual((rem['has_documented_fix'], rem['cisa_required_action']), (True, 'Apply updates.'))
        self.assertEqual(self.row['credits'], [{'type': 'finder', 'name': 'A. Researcher'}])
        self.assertEqual([(c['repo'], c['commit']) for c in self.row['fix_commits']],
                         [('https://github.com/acme/gateway', 'abcdef1234567890')])
        self.assertEqual(self.row['repositories'], ['https://github.com/acme/gateway'])
        self.assertEqual(self.row['exploit_summary']['maturity'], 'exploited in the wild')
        self.assertEqual(self.rows['CVE-2025-0021']['exploit_summary']['maturity'], 'none known')
        self.assertEqual(self.row['timeline']['days_to_kev'], 31)
        tl = self.row['timeline']
        self.assertEqual((tl['reserved'][:10], tl['kev_added'], tl['kev_due']), ('2025-01-01', '2025-04-01', '2025-04-22'))

    def test_products_carry_uniform_ranges(self):
        gw = self.row['products'][0]
        self.assertEqual(gw['types'], ['hardware'])
        self.assertIn({'source': 'acme', 'status': 'affected', 'type': 'semver', 'introduced': '1.0', 'fixed': '1.4'}, gw['ranges'])
        self.assertIn({'source': 'NVD', 'status': 'affected', 'versions': ['2.0']}, gw['ranges'])
        self.assertIn({'source': 'acme', 'status': 'unaffected', 'versions': ['1.3.9']}, gw['ranges'])

    def test_product_lists_placeholders_and_commit_fixes(self):
        row = {**vg.BLANK, 'affected': [
            {'vendor': 'Huawei', 'product': 'AP2000;IPS Module;NGFW Module', 'source': 'huawei',
             'versions': [{'version': '0', 'lessThan': 'n/a', 'status': 'affected'}]},
            {'vendor': 'Linux', 'product': 'Linux', 'source': 'Linux', 'repo': 'https://git.kernel.org/x',
             'versions': [{'version': 'abc', 'lessThan': '1c973f9c7cc2b3caae93192fdc8ecb3f0b4ac000', 'status': 'affected',
                           'versionType': 'git'}]}]}
        prods = {p['product_key']: p for p in vg.row_products(row)}
        self.assertEqual(sorted(prods), ['huawei:ap2000', 'huawei:ips module', 'huawei:ngfw module', 'linux:kernel'])
        self.assertEqual(prods['huawei:ap2000']['fixed'], [])
        self.assertEqual((prods['linux:kernel']['fixed'], prods['linux:kernel']['fixed_commits']),
                         ([], ['1c973f9c7cc2b3caae93192fdc8ecb3f0b4ac000']))

    def test_summary_and_attack_techniques(self):
        self.assertEqual(self.row['summary'], 'Memory corruption in gateway (acme), reachable over the network without '
                         'authentication. Critical (CVSS 9.8, acme). Known to be exploited (CISA KEV). '
                         'Fixed versions or patches documented.')
        self.assertEqual(self.row['attack_techniques'],
                         [{'id': 'T1499', 'name': 'Endpoint Denial of Service', 'via': 'CAPEC-100'}])

    def test_product_index_has_one_line_per_product_and_vulnerability(self):
        self.assertEqual(sorted((x['product_key'], x['id']) for x in self.index),
                         [('acme:gateway', 'CVE-2025-0020'), ('acme:gateway', 'CVE-2025-0021')])
        first = next(x for x in self.index if x['id'] == 'CVE-2025-0020')
        self.assertEqual((first['score'], first['priority'], first['kev'], first['fixed']), (9.8, 'act now', True, ['1.3.9', '1.4']))

    def test_vendor_and_weakness_aggregates(self):
        v = self.vendors['acme']
        self.assertEqual((v['total'], v['kev'], v['exploited'], v['remote_unauthenticated']), (2, 1, 1, 1))
        self.assertEqual(v['top_products'], {'acme:gateway': 2})
        self.assertEqual(self.weak['CWE-9999']['class'], 'memory corruption')
        self.assertEqual(self.weak['CWE-121']['total'], 1)


class AuditFixTests(unittest.TestCase):
    """Regressions found by the full dataset audits."""

    def test_fixed_version_keeps_the_version_token(self):
        self.assertEqual(vg.fixed_version('macOS Mojave 10.14.5'), '10.14.5')
        self.assertIsNone(vg.fixed_version('publication'))
        self.assertIsNone(vg.fixed_version('log4j-core*'))
        self.assertEqual(vg.fixed_version('2.15.0'), '2.15.0')

    def test_product_names_lose_version_tails_and_vendor_colons(self):
        row = {**vg.BLANK, 'affected': [
            {'vendor': 'Adobe', 'product': 'Adobe Flash Player 24.0.0.194 and earlier.'},
            {'vendor': 'n/a', 'product': '15.023.20070 and earlier.'},
            {'vendor': 'UFO: Alien Invasion Project', 'product': 'UFO AI'}]}
        self.assertEqual([p['product_key'] for p in vg.row_products(row)],
                         ['adobe:flash player', 'ufo alien invasion:ufo ai'])

    def test_vendorless_product_takes_the_assigner_vendor(self):
        row = {**vg.BLANK, 'assigner': 'apple', 'affected': [{'vendor': 'n/a', 'product': 'tvOS'}],
               'nvd_cpe': [{'criteria': 'cpe:2.3:o:apple:tvos:*:*:*:*:*:*:*:*', 'versionEndExcluding': '17.2'},
                           {'criteria': 'cpe:2.3:o:apple:watchos:*:*:*:*:*:*:*:*'}]}
        products = {p['product_key']: p for p in vg.row_products(row)}
        self.assertEqual(sorted(products), ['apple:tvos', 'apple:watchos'])
        self.assertIn(':tvos', products['apple:tvos']['names'])

    def test_vendorless_rules_and_repository_urls(self):
        row = {**vg.BLANK, 'assigner': 'google_android', 'affected': [
            {'vendor': 'n/a', 'product': 'MT6873'}, {'vendor': 'n/a', 'product': 'Intel Processors'},
            {'vendor': 'n/a', 'product': 'https://github.com/curl/curl'}]}
        self.assertEqual([p['product_key'] for p in vg.row_products(row)],
                         ['curl:curl', 'intel:processors', 'mediatek:mt6873'])

    def test_score_that_its_vector_does_not_give_is_flagged(self):
        row = {**vg.BLANK, 'cvss': [{'source': 'x', 'version': '3.1', 'score': 9.8,
                                     'vector': 'CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N'},
                                    {'source': 'y', 'version': '4.0', 'score': 9.3,
                                     'vector': 'CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/E:P'}]}
        vg.enrich(row, {})
        self.assertEqual(row['cvss'][0]['vector_score'], 5.5)
        self.assertNotIn('vector_score', row['cvss'][1])  # base score, threat metric E left out as CNAs do

    def test_editions_in_parentheses_are_not_split_into_products(self):
        row = {**vg.BLANK, 'affected': [{'vendor': 'F5', 'product': 'BIG-IP (LTM, AAM, AFM, APM)'}]}
        self.assertEqual([p['product_key'] for p in vg.row_products(row)], ['f5:big-ip'])
        self.assertEqual(vg.norm_repo('git://github.com/lpereira/lwan'), 'https://github.com/lpereira/lwan')
        self.assertEqual(vg.strip_parens('otrs (( otrs )) community edition'), 'otrs community edition')
        self.assertEqual(vg.strip_parens('arcsight esm (when arcsight fusion'), 'arcsight esm')
        row = {**vg.BLANK, 'affected': [{'vendor': 'Xiaomi', 'product': 'Redmi K40 ,Redmi Note10 Pro'},
                                        {'vendor': 'LG', 'product': '(LGPCSuite_Setup), (IPSFULLHD, LG_ULTRAWIDE)'}]}
        self.assertEqual([p['product_key'] for p in vg.row_products(row)],
                         ['lg:ipsfullhd', 'lg:lgpcsuite setup', 'lg:ultrawide', 'xiaomi:redmi k40', 'xiaomi:redmi note10 pro'])

    def test_placeholder_zero_score_is_never_primary(self):
        row = {**vg.BLANK, 'assigner': 'GitHub_M', 'cvss': [
            {'source': 'GitHub_M', 'version': '3.1', 'score': 0, 'vector': 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N'},
            {'source': 'NVD', 'version': '3.1', 'score': 9.8, 'vector': 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H'}]}
        self.assertEqual(vg.primary_cvss(row)['source'], 'NVD')
        only_zero = {**row, 'cvss': row['cvss'][:1]}
        self.assertEqual(vg.primary_cvss(only_zero)['score'], 0)
        self.assertEqual(vg.family('borland software corporation:interbase'), 'borland:interbase')
        self.assertEqual(vg.family('k5n.us:webcalendar'), 'k5n:webcalendar')

    def test_osv_range_without_bounds_is_every_version(self):
        self.assertEqual(vg.osv_ranges({'ranges': [{'type': 'SEMVER', 'events': [{'introduced': '0'}]}]}),
                         [{'status': 'affected', 'type': 'semver', 'introduced': None, 'any_version': True}])

    def test_git_fix_gets_a_commit_url(self):
        row = {**vg.BLANK, 'packages': [{'source': 'X', 'git_fixes': [{'repo': 'https://github.com/a/b', 'commit': 'a' * 40}]}]}
        self.assertEqual(vg.fix_commits(row)[0]['url'], 'https://github.com/a/b/commit/' + 'a' * 40)


if __name__ == '__main__':
    unittest.main()
