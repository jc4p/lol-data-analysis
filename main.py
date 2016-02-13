from riotwatcher import RiotWatcher, NORTH_AMERICA, KOREA, EUROPE_WEST
from datetime import datetime, timedelta
from little_pger import LittlePGer
from pprint import pprint
import random
import json
import redis
import time
import os

REDIS_URL = os.environ.get('REDIS_URL', '')
if REDIS_URL:
    redis = redis.from_url(REDIS_URL)
else:
    redis = redis.StrictRedis(host='localhost', port=6379, db=0)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
RIOT_API_KEY = os.environ.get('RIOT_API_KEY', '')
riot = RiotWatcher(RIOT_API_KEY)

def get_static(cache_ignore=False):
    if not cache_ignore:
        champions = redis.get('static_champions')
        items = redis.get('static_items')
        if champions and items:
            champions = json.loads(champions)
            items = json.loads(items)
            items = {int(x):y for x,y in items.iteritems()}
            return champions, items

    champions = riot.static_get_champion_list(champ_data='tags,info')['data']
    items = riot.static_get_item_list(item_list_data='depth,from')['data']
    items = {int(x):y for x,y in items.iteritems()}
    redis.set('static_champions', json.dumps(champions))
    redis.set('static_items', json.dumps(items))
    return champions, items

champion_data, item_data = get_static(cache_ignore=True)
champion_data_by_id = {y['id']:y for x,y in champion_data.iteritems()}


def get_players(cache_ignore=False):
    if not cache_ignore:
        players_by_region = redis.hgetall('players_by_region')
        if players_by_region and len(players_by_region.keys()) == 3:
            players_by_region = {x: json.loads(y) for x,y in players_by_region.iteritems()}
            if all([len(y) > 0 for x,y in players_by_region.iteritems()]):
                return players_by_region

    players_by_region = {NORTH_AMERICA: [], KOREA: [], EUROPE_WEST: []}

    for region in players_by_region.keys():
        players = []
        challengers = riot.get_challenger(region=region)
        masters = riot.get_master(region=region)
        for p in challengers['entries'] + masters['entries']:
            player = {'name': p['playerOrTeamName'], 'id': p['playerOrTeamId']}
            players.append(player)
        redis.hset('players_by_region', region, json.dumps(players))
        players_by_region[region] = players

    return players_by_region


def get_matches_for_champion(players, champ, begin_time=datetime.utcnow() - timedelta(weeks=1), cache_ignore=False):
    if not cache_ignore:
        keys = redis.hkeys('player_matches')
        if keys:
            champ_keys = [x for x in keys if "_{}".format(champ['id']) in x]
            if len(champ_keys) > 10:
                matches = []
                for k,v in redis.hscan_iter('player_matches', '*_{}'.format(champ['id'])):
                    if v:
                        matches += json.loads(v)
                return matches

    matches = []

    last_week = int(time.mktime(begin_time.timetuple())) * 1000
    for region in players.keys():
        for player in players[region]:
            if not cache_ignore:
                this_player = redis.hget('player_matches', "{}_{}".format(player['id'], champ['id']))
                if this_player:
                    print u"CACHE HIT - {}'s {} matches".format(player['name'], champ['name']).encode("utf-8")
                    matches += this_player
                    continue

            print u"NETWORK - {}'s {} matches".format(player['name'], champ['name']).encode("utf-8")

            this_player = []
            page = riot.get_match_list(player['id'], region=region, champion_ids=champ['id'], ranked_queues='TEAM_BUILDER_DRAFT_RANKED_5x5', begin_time=last_week)
            while 'matches' in page.keys() and page['matches']:
                for m in page['matches']:
                    if m['champion'] != champ['id'] or m['queue'] == 'CUSTOM':
                        continue
                    this_player.append({'lane': m['lane'], 'matchId': m['matchId'], 'region': m['region'], 'role': m['role']})
                if len(this_player) == page['totalGames']:
                    break
                time.sleep(1)
                print u"NETWORK INNER - {}'s {} matches".format(player['name'], champ['name']).encode("utf-8")
                page = riot.get_match_list(player['id'], region=region, champion_ids=champ['id'], ranked_queues='TEAM_BUILDER_DRAFT_RANKED_5x5', begin_time=last_week, begin_index=page['endIndex'])
            if this_player:
                redis.hset('player_matches', "{}_{}".format(player['id'], champ['id']), json.dumps(this_player))
                matches += this_player
            time.sleep(2)

    return matches


def save_matches_info(matches, champ):
    for m in matches:
        if "{}_{}_{}".format(m['region'], m['matchId'], champ['id']) in redis.hkeys('match_details'):
            continue
        match = redis.hget('match_infos', '{}_{}'.format(m['region'], m['matchId']))
        if match:
            match = json.loads(match)
        else:
            match = riot.get_match(m['matchId'], region=m['region'].lower(), include_timeline=True)
            redis.hset('match_infos', '{}_{}'.format(m['region'], m['matchId']), json.dumps(match))
        participantId = None
        participant = None
        for p in match['participants']:
            if p['championId'] == champ['id']:
                participant = p
                participantId = p['participantId']
                break
        team = None
        for t in match['teams']:
            if t['teamId'] == participant['teamId']:
                team = t
                break

        won = team['winner']
        stats = participant['stats']
        kills, deaths, assists = stats['kills'], stats['deaths'], stats['assists']
        first_blood = stats['firstBloodKill']
        first_blood_assist = stats['firstBloodAssist']

        tanks_friendly_team = 0
        tanks_enemy_team = 0
        lane_partner = None
        for p in match['participants']:
            friendly = p['teamId'] == participant['teamId']
            tags = champion_data_by_id[p['championId']]
            if 'Tank' in tags:
                if friendly:
                    tanks_friendly_team += 1
                else:
                    tanks_enemy_team += 1

            if friendly:
                continue

            lane, role = None, None
            for t in p['timeline']:
                if 'lane' not in t or 'role' not in t:
                    continue
                lane = t['lane']
                role = t['role']
                break
            if not (lane and role):
                continue
            raise ValueError('{}, {}'.format(lane, role))
            if lane == m['lane'] and role == m['role']:
                lane_partner = p
                break

        if lane_partner:
            lane_partner_champ = champion_data_by_id[lane_partner['championId']]
            lane_partner_ad = lane_partner_champ['info']['attack'] > lane_partner['info']['magic']
        else:
            lane_partner_ad = False

        items = []
        for e in match['timeline']['frames']:
            if 'events' not in e.keys():
                continue
            for ev in e['events']:
                if ev['eventType'] == 'ITEM_PURCHASED' and ev['participantId'] == participantId:
                    # I don't care about biscuits or health potions or wards or trinkets
                    if ev['itemId'] in (2003, 2010, 2043, 3340, 3341, 3361, 3362, 3363, 3364):
                        continue
                    item_info = item_data[ev['itemId']]
                    # Don't care about base items, only upgrades
                    if 'depth' not in item_info:
                        continue
                    # Don't care about level 3 boot upgrades
                    if 'group' in item_info and 'boots' in item_info['group'].lower():
                        continue
                    items.append(ev['itemId'])

        trimmed_items = []
        for i, item_id in enumerate(items):
            item = item_data[item_id]

            prev_items = trimmed_items[:]
            if prev_items and 'from' in item:
                # if the last few items all build into this item, but they're
                # different parts of the tree (i.e. they don't upgrade into each other)
                # we shouldn't have the entire build path in the item list
                from_items = item['from']
                last_item = prev_items.pop()
                while str(last_item) in from_items:
                    if 'from' in item_data[last_item]:
                        from_items += item_data[last_item]['from']
                    trimmed_items.remove(last_item)
                    if not prev_items:
                        break
                    last_item = prev_items.pop()
            prev_items = trimmed_items[:]
            if prev_items and 'from' in item:
                # if the N-1th or N-2nd item is something that upgrades into this, skip it
                last_item = prev_items.pop()
                last_last_item = prev_items.pop() if prev_items else None

                if str(last_item) in item['from']:
                    trimmed_items.remove(last_item)
                if str(last_last_item) in item['from']:
                    trimmed_items.remove(last_last_item)

            trimmed_items.append(item_id)

        items = trimmed_items

        details = {
            'championId': champ['id'],
            'won': won,
            'duration': match['matchDuration'],
            'kills': kills,
            'deaths': deaths,
            'assists': assists,
            'first_blood_kill': first_blood,
            'first_blood_assist': first_blood_assist,
            'lane_enemy_ad': lane_partner_ad,
            'purchases': items
        }

        redis.hset('match_details', "{}_{}_{}".format(m['region'], m['matchId'], champ['id']), json.dumps(details))
        print "Parsed and saved match {}\n".format(m['matchId'])
        pprint(details)
        print "-" * 30


if __name__ == "__main__":
    players = get_players()
    print "{} players found".format(sum([len(y) for x,y in players.iteritems()]))

    matches = get_matches_for_champion(players, champion_data['Viktor'])
    print "Got {} Viktor matches".format(len(matches))
    save_matches_info(matches, champion_data['Viktor'])
    print "Saved {} match infos".format(len(matches))

