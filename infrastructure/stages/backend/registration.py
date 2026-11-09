"""Source-declared registration types bound to server-owned roles and organizations."""


def registration_config(plan, evidence):
    config = plan.get('registration') or {'enabled': False, 'user_types': []}
    if not config.get('enabled'):
        return {'enabled': False, 'user_types': []}
    catalog = evidence['authorization']['catalog']
    roles = {row['id'] for row in catalog['roles']}
    units = {row['id'] for row in catalog['units']}
    known = set(evidence['nodes'])
    result, seen = [], set()
    for row in config.get('user_types', []):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in seen:
            raise ValueError('Registration needs unique user type IDs')
        if not row.get('label') or row.get('role') not in roles or row.get('unit') not in units:
            raise ValueError('Registration types require existing source roles and units')
        if not row.get('requirements') or not set(row['requirements']) <= known or not row.get('source_refs'):
            raise ValueError('Registration mapping requires original requirement evidence')
        # Privileged account creation stays admin-managed. Public clients never choose
        # arbitrary role/unit IDs, even when those values exist in the source catalog.
        if row['role'] == 'admin':
            raise ValueError('Public registration cannot issue administrator memberships; use administrator-managed account creation')
        seen.add(row['id'])
        result.append({key: row[key] for key in ('id', 'label', 'role', 'unit', 'requirements', 'source_refs')})
    if not result:
        raise ValueError('Enabled registration must declare at least one allowed user type')
    return {'enabled': True, 'user_types': result}
