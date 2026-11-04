"""New controlled English cases with explicit, reviewable semantic models.

Labels are derived by enumerating models, then independently checked using Z3.
Natural-language/formula alignment is authored, not independently human-adjudicated.
Four lexical instances of each template are NOT treated as independent templates.
"""
from itertools import product
import hashlib
import json

LABELS = ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')
MECHANISMS = {
    'basic': ('BOUND', 'FUNCTIONAL', 'IMPLICATIVE', 'PLACE', 'PLAN', 'RELDATE', 'TIMESHIFT'),
    'challenge': ('AMBIGREF', 'DENIAL', 'LOOKALIKE', 'PRESUP', 'SETCLOSE', 'TEMPSCOPE', 'UNIQUE'),
}
PEOPLE = [('Mira Vale', 'Owen Vale', 'Tessa Rowan'), ('Lena Fenn', 'Ivo Fenn', 'Nora Reed'),
          ('Ada Rill', 'Evan Rill', 'Cora Finch'), ('Vera Moss', 'Leon Moss', 'Iris Hart')]
PLACES = [('Aster', 'Brindle'), ('Cedar', 'Dovetail'), ('Elm', 'Fable'), ('Grove', 'Harbor')]

def neg(x): return ['not', x]
def conj(*xs): return ['and', *xs]
def disj(*xs): return ['or', *xs]
def implies(a, b): return ['implies', a, b]
def eq(a, b): return ['eq', a, b]

def evaluate(expr, env):
    if isinstance(expr, str): return env[expr]
    if isinstance(expr, (int, bool)): return expr
    op, *args = expr
    values = [evaluate(x, env) for x in args]
    if op == 'not': return not values[0]
    if op == 'and': return all(values)
    if op == 'or': return any(values)
    if op == 'implies': return not values[0] or values[1]
    if op == 'eq': return values[0] == values[1]
    if op == 'ge': return values[0] >= values[1]
    if op == 'le': return values[0] <= values[1]
    if op == 'lt': return values[0] < values[1]
    raise ValueError(op)

def variables(expr):
    if isinstance(expr, str): return {expr}
    if isinstance(expr, list): return set().union(*(variables(x) for x in expr[1:]))
    return set()

def truth_label(premise, claim, integers=()):
    names = sorted(variables(premise) | variables(claim))
    domains = [range(51) if name in integers else (False, True) for name in names]
    outcomes, witnesses = set(), {}
    for vals in product(*domains):
        env = dict(zip(names, vals))
        if evaluate(premise, env):
            truth = bool(evaluate(claim, env))
            outcomes.add(truth)
            witnesses.setdefault(str(truth).lower(), env)
    if not outcomes: raise ValueError('Inconsistent evidence')
    label = 'SUPPORTS' if outcomes == {True} else 'REFUTES' if outcomes == {False} else 'NOT ENOUGH INFO'
    return label, witnesses

def build_template(dataset, mechanism, style, instance):
    """Return claim and three evidence/formula pairs, with S/R/N design expectations."""
    a, b, c = PEOPLE[instance]
    city, other = PLACES[instance]
    award = f'{city} Medal'
    year = 2031 + instance * 3
    k = 12 + instance * 3
    q, p = 'q', 'p'
    integers = ()
    target = q
    if dataset == 'challenge':
        if mechanism == 'DENIAL':
            verb = 'denied' if style == 0 else 'dismissed as false'
            event = f'{a} opened the {city} museum' if style == 0 else f'{a} donated a painting to the {city} museum'
            base = f'A spokesperson {verb} the report that {event}. '
            claim = event + '.'
            cases = [(base + f'Independent records establish that {event}.', conj('denial', q)),
                     (base + f'Independent records establish that it is false that {event}.', conj('denial', neg(q))),
                     (base.rstrip(), 'denial')]
        elif mechanism == 'AMBIGREF':
            if style == 0:
                base = f'{a}, a woman, visited {city} with her brother {b}. He received the {award} that year. '
                claim = f'{a} received the {award} that year.'
            else:
                base = f'{b}, a man, worked with his sister {a} on a documentary. She received the {award} for that documentary. '
                claim = f'{b} received the {award} for that documentary.'
            base_person = a if style == 0 else b
            actual = b if style == 0 else a
            cases = [(base + f'{base_person} also received that same medal for the same occasion.', conj(p, q)),
                     (base + f'{actual} was the sole recipient of that medal on that occasion.', conj(p, neg(q))),
                     (base.rstrip(), p)]
        elif mechanism == 'LOOKALIKE':
            claim = f'{a} received the {award} in {year}.'
            if style == 0:
                base = f'{b} received the {award} in {year}. '
                cases = [(base + f'{a}, a different person, also received that medal in {year}.', conj(p, q)),
                         (base + f'{b} was its only recipient in {year}; {a} and {b} are different people.', conj(p, neg(q))),
                         (base + f'{a} and {b} are different people.', p)]
            else:
                base = f'{b} was the only member of the {city} household to receive the {award} in {year}. '
                rule = implies('member', neg(q))
                cases = [(base + f'{a} belongs to another household and also received that medal in {year}.', conj(p, rule, neg('member'), q)),
                         (base + f'{a} is a different person and a member of the {city} household.', conj(p, rule, 'member')),
                         (base + f'{a} is a different person with the same surname as {b}.', conj(p, rule))]
        elif mechanism == 'PRESUP':
            action = f'won the {award}' if style == 0 else f'exhibited at the {city} gallery'
            claim = f'{a} had {action} before {year}.'
            base = f'{a} {action} in {year}. '
            first = f'This was the first time in her life that she {action}.'
            earlier = f'She had also {action} in {year - 4}.'
            cases = [(base + earlier, conj(p, q)), (base + first, conj(p, neg(q))), (base.rstrip(), p)]
        elif mechanism == 'SETCLOSE':
            if style == 0:
                claim = f'{c} is one of {b}\'s children.'
                base = f'{b} has exactly two children born between {year} and {year + 4}, inclusive: {a} and Niko. '
                cases = [(base + f'{c}, born in {year - 7}, is another child of {b}.', conj(p, q)),
                         (f'{b} has exactly two children in total: {a} and Niko. {c} is a different person from each of them.', neg(q)),
                         (base + f'{c} is a different person from each of them.', p)]
            else:
                claim = f'The Lumen project won a {city} grant in {year}.'
                base = f'Exactly two software projects won {city} grants in {year}: Kite and Moth. '
                cases = [(base + f'Lumen, a separate sculpture project, also won a {city} grant in {year}.', conj(p, q)),
                         (f'The complete list of projects receiving any {city} grant in {year} contains exactly Kite and Moth. Lumen is a different project.', neg(q)),
                         (base + 'Lumen is a different project.', p)]
        elif mechanism == 'TEMPSCOPE':
            action = f'director of the {city} museum' if style == 0 else f'editor of the {city} journal'
            claim = f'{a} served as {action} in {year + 6}.'
            base = f'{a}\'s first term as {action} ran from {year} through {year + 2}. '
            cases = [(base + f'Her second term in that position ran from {year + 5} through {year + 8}.', conj(p, q)),
                     (f'{a}\'s only term ever as {action} ran from {year} through {year + 2}.', neg(q)),
                     (base.rstrip(), p)]
        elif mechanism == 'UNIQUE':
            if style == 0:
                claim = f'{a} completed the {city} race in {year}.'
                base = f'{b} was the only member of the {other} club to complete the {city} race in {year}. '
                rule = implies('member', neg(q))
                cases = [(base + f'{a}, who belongs to another club, also completed that race.', conj(p, rule, neg('member'), q)),
                         (base + f'{a} is a different person and a member of the {other} club.', conj(p, rule, 'member')),
                         (base + f'{a} is a different person.', conj(p, rule))]
            else:
                claim = f'Team {other} completed the final puzzle.'
                base = f'Team {city} completed the final puzzle. '
                cases = [(base + f'Team {other} completed it too.', conj(p, q)),
                         (base + f'Exactly one of the two teams, {city} and {other}, completed it.', conj(p, neg(q))),
                         (base + f'At least one of the two teams, {city} and {other}, completed it.', p)]
    else:
        if mechanism == 'BOUND':
            integers = ('n',)
            if style == 0:
                claim = f'The {city} box contains at least {k} coins.'
                target = ['ge', 'n', k]
                cases = [(f'The {city} box contains exactly {k + 2} coins.', eq('n', k + 2)),
                         (f'The {city} box contains at most {k - 1} coins.', ['le', 'n', k - 1]),
                         (f'The {city} box contains at most {k + 2} coins.', ['le', 'n', k + 2])]
            else:
                claim = f'Fewer than {k} people attended the {city} meeting.'
                target = ['lt', 'n', k]
                cases = [(f'Exactly {k - 2} people attended the {city} meeting.', eq('n', k - 2)),
                         (f'At least {k} people attended the {city} meeting.', ['ge', 'n', k]),
                         (f'At least {k - 2} people attended the {city} meeting.', ['ge', 'n', k - 2])]
        elif mechanism == 'FUNCTIONAL':
            if style == 0:
                claim = f'{a} is the registered owner of drone {city}.'
                base = f'Drone {city} has exactly one registered owner. {a} and {b} are different people. '
                rule = neg(conj(p, q))
                cases = [(base + f'That owner is {a}.', conj(rule, q)),
                         (base + f'That owner is {b}.', conj(rule, p)),
                         (base + f'That owner is either {a} or {b}.', conj(rule, disj(p, q)))]
            else:
                claim = f'{city} is the sole administrative capital of the {other} district.'
                base = f'The {other} district has exactly one administrative capital. {city} and Juniper are different cities. '
                rule = neg(conj(p, q))
                cases = [(base + f'The capital is {city}.', conj(rule, q)),
                         (base + 'The capital is Juniper.', conj(rule, p)),
                         (base + f'The capital is either {city} or Juniper.', conj(rule, disj(p, q)))]
        elif mechanism == 'IMPLICATIVE':
            if style == 0:
                claim = f'Badge {city} is valid.'
                rule = implies(p, q)
                base = f'If badge {city} bears a blue seal, it is valid. '
                cases = [(base + 'It bears a blue seal.', conj(rule, p)),
                         (base + 'The badge is not valid.', conj(rule, neg(q))),
                         (base + 'It does not bear a blue seal.', conj(rule, neg(p)))]
            else:
                claim = f'Sensor {city} is active.'
                rule = implies(q, p)
                base = f'If sensor {city} is active, its lamp is lit. '
                cases = [(base + 'The sensor is active.', conj(rule, q)),
                         (base + 'Its lamp is not lit.', conj(rule, neg(p))),
                         (base + 'Its lamp is lit.', conj(rule, p))]
        elif mechanism == 'PLACE':
            if style == 0:
                claim = f'The parcel is currently in {city} province.'
                base = f'{other} town lies entirely within {city} province. '
                rule = implies(p, q)
                cases = [(base + f'The parcel is currently in {other} town.', conj(rule, p)),
                         (base + f'The parcel is currently outside {city} province.', conj(rule, neg(q))),
                         (base + f'The parcel was sent from {other} town last week.', conj(rule, 'past'))]
            else:
                claim = f'The key is inside the {city} building.'
                base = f'The {other} room is wholly inside the {city} building. '
                rule = implies(p, q)
                cases = [(base + f'The key is in the {other} room.', conj(rule, p)),
                         (base + f'The key is outside the {city} building.', conj(rule, neg(q))),
                         (base + f'The key is not in the {other} room.', conj(rule, neg(p)))]
        elif mechanism == 'PLAN':
            if style == 0:
                claim = f'{a} visited {city} in {year}.'
                base = f'{a} planned to visit {city} in {year}. '
                cases = [(base + 'She carried out that visit that year.', conj(p, q)),
                         (base + f'She never visited {city} during {year}.', conj(p, neg(q))),
                         (base.rstrip(), p)]
            else:
                claim = f'The {city} concert took place on 12 May {year}.'
                base = f'The {city} concert was scheduled for 12 May {year}. '
                cases = [(base + 'The concert took place on that date.', conj(p, q)),
                         (base + 'The concert did not take place on that date.', conj(p, neg(q))),
                         (base.rstrip(), p)]
        elif mechanism == 'RELDATE':
            integers = ('day',)
            if style == 0:
                claim = f'The {city} package arrived before {k} June {year}.'
                target = ['lt', 'day', k]
                cases = [(f'The {city} package arrived on {k - 2} June {year}.', eq('day', k - 2)),
                         (f'The {city} package arrived on {k + 2} June {year}.', eq('day', k + 2)),
                         (f'The {city} package arrived sometime from {k - 2} through {k + 2} June {year}, inclusive.', conj(['ge', 'day', k - 2], ['le', 'day', k + 2]))]
            else:
                claim = f'The {city} exhibition opened on {k + 3} June {year}.'
                target = eq('day', k + 3)
                base = f'The {city} exhibition was announced on {k} June {year}. '
                cases = [(base + 'It opened three days after the announcement.', eq('day', k + 3)),
                         (base + 'It opened five days after the announcement.', eq('day', k + 5)),
                         (base + 'It opened either three or five days after the announcement.', disj(eq('day', k + 3), eq('day', k + 5)))]
        elif mechanism == 'TIMESHIFT':
            if style == 0:
                claim = f'{a} was director of the {city} archive in June {year + 2}.'
                cases = [(f'{a} served continuously as director of the {city} archive from January {year} through December {year + 4}.', q),
                         (f'{a}\'s only period ever as director of the {city} archive was January {year} through December {year + 1}.', neg(q)),
                         (f'{a} was director of the {city} archive in June {year}.', p)]
            else:
                claim = f'The {city} branch was open on 15 July {year}.'
                cases = [(f'The {city} branch was open every day from 1 July through 31 July {year}.', q),
                         (f'The {city} branch was closed every day from 1 July through 31 July {year}.', neg(q)),
                         (f'The {city} branch was open on 14 July {year}.', p)]
    return claim, cases, target, integers

def generate():
    result = []
    for dataset, mechanisms in MECHANISMS.items():
        for mechanism in mechanisms:
            for style in range(2):
                family = f'{dataset}/{mechanism}/t{style + 1}'
                for instance in range(4):
                    claim, cases, formula, integers = build_template(dataset, mechanism, style, instance)
                    group = f'{family}/s{instance + 1}'
                    for expected, (evidence, premise) in zip(LABELS, cases):
                        label, witnesses = truth_label(premise, formula, integers)
                        assert label == expected, (group, expected, label)
                        identifier = hashlib.sha256((evidence + '\0' + claim).encode()).hexdigest()[:20]
                        result.append({'id': 'ctrl_' + identifier, 'dataset': dataset, 'group': group,
                                       'template_family': family, 'mechanism': mechanism, 'label': label,
                                       'evidence': evidence, 'claim': claim,
                                       'semantics': {'premise': premise, 'claim': formula, 'integers': list(integers),
                                                     'witnesses': witnesses}})
    assert len(result) == 336 and len({r['id'] for r in result}) == 336
    return sorted(result, key=lambda r: hashlib.sha256(('order-v15-20261030' + r['id']).encode()).hexdigest())
