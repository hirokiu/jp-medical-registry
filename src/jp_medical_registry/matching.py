"""Conservative matching of preselected Wikidata candidates, not fuzzy auto-linking."""
import re
import unicodedata


def normalized_name(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def values(entity, prop):
    return [c.get('mainsnak', {}).get('datavalue', {}).get('value')
            for c in entity.get('claims', {}).get(prop, []) if c.get('rank') != 'deprecated']


def assess(record, candidates):
    """Only code+name agreement without postal/phone contradictions can confirm.

    Candidates must already have been retrieved/reviewed. This function does not
    assert that Wikidata has no additional matches elsewhere.
    """
    assessments = []
    for entity in candidates:
        code_match = record['insurance_id'] in values(entity, 'P13179')
        names = [v['value'] for v in entity.get('labels', {}).values()]
        names += [v['value'] for group in entity.get('aliases', {}).values() for v in group]
        names += [v['text'] for v in values(entity, 'P1448') if isinstance(v, dict) and 'text' in v]
        name_match = normalized_name(record['name']) in {normalized_name(n) for n in names}
        conflicts = []
        if record.get('postal_code'):
            postals = {re.sub(r'\D', '', str(v)) for v in values(entity, 'P281')}
            if postals and re.sub(r'\D', '', record['postal_code']) not in postals:
                conflicts.append('postal_code')
        if record.get('phone'):
            def phone(v):
                v = re.sub(r'[^0-9+]', '', unicodedata.normalize('NFKC', v))
                return '+81' + v[1:] if v.startswith('0') else v
            phones = {phone(str(v)) for v in values(entity, 'P1329')}
            if phones and phone(record['phone']) not in phones:
                conflicts.append('phone')
        assessments.append({'qid': entity['id'], 'code_match': code_match,
                            'name_match': name_match, 'conflicts': conflicts,
                            'wikidata_revision': entity.get('lastrevid')})
    hits = [a for a in assessments if a['code_match']]
    confirmed = len(hits) == 1 and hits[0]['name_match'] and not hits[0]['conflicts']
    return {'status': 'confirmed' if confirmed else 'review_required' if assessments else 'not_checked',
            'qid': hits[0]['qid'] if confirmed else None,
            'method': 'reviewed-candidate/code-and-normalized-name-v1',
            'scope': 'supplied candidates only; no probabilistic confidence assigned',
            'evidence': assessments}
