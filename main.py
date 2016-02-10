from riotwatcher import RiotWatcher, NORTH_AMERICA, KOREA, EUROPE_WEST
from datetime import datetime, timedelta
from little_pger import LittlePGer
from pprint import pprint
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
            return json.loads(champions), json.loads(items)

    champions = riot.static_get_champion_list()['data']
    items = riot.static_get_item_list()['data']
    redis.set('static_champions', json.dumps(champions))
    redis.set('static_items', json.dumps(items))
    return champions, items


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


# def create_tables():
    # with LittlePGer(conn=DATABASE_URL) as pg:
    #     pg.cursor.execute("CREATE TABLE IF NOT EXISTS matches;")


def save_matches_info(matches, champ):
    all_items = []
    for m in matches[:5]:
        match = redis.hget('match_infos', '{}_{}'.format(m['region'], m['matchId']))
        if match:
            match = json.loads(match)
        else:
            match = riot.get_match(m['matchId'], region=m['region'].lower(), include_timeline=True)
            redis.hset('match_infos', '{}_{}'.format(m['region'], m['matchId']), json.dumps(match))
        participantId = None
        for p in match['participants']:
            if p['championId'] == champ['id']:
                participantId = p['participantId']
                break
        if not participantId:
            print "Uhh no {} in this {}/{}".format(champ['name'], m['region'], m['matchId'])
            return

        items = []
        for e in match['timeline']['frames']:
            if 'events' not in e.keys():
                continue
            for ev in e['events']:
                if ev['eventType'] == 'ITEM_PURCHASED' and ev['participantId'] == participantId:
                    # I don't care about biscuits or health potions or wards or trinkets
                    if ev['itemId'] in (2003, 2010, 2043, 3340, 3341, 3361, 3362, 3363, 3364):
                        continue
                    items.append(ev['itemId'])
        all_items.append(items)
    return all_items


if __name__ == "__main__":
    champions, items = get_static()
    players = get_players()
    print "{} players found".format(sum([len(y) for x,y in players.iteritems()]))

    matches = get_matches_for_champion(players, champions['Viktor'])
    print "Got {} Viktor matches".format(len(matches))
    # create_tables()
    items_bought = save_matches_info(matches, champions['Viktor'])
    for game in items_bought:
        print " > ".join([items[str(x)]['name'] for x in game])
        print ""
