from riotwatcher import RiotWatcher, NORTH_AMERICA, KOREA, EUROPE_WEST
from datetime import datetime, timedelta
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
        matches = redis.hget('matches', champ['id'])
        if matches:
            return json.loads(matches)

    matches = []

    last_week = int(time.mktime(begin_time.timetuple())) * 1000
    for region in players.keys():
        for player in players[region]:
            if not cache_ignore:
                this_player = redis.hget('player_matches', "{}_{}".format(player['id'], champ['id']))
                if this_player:
                    print "CACHE HIT - {}'s {} matches".format(player['name'], champ['name'])
                    matches += this_player
                    continue

            print "NETWORK - {}'s {} matches".format(player['name'], champ['name'])

            this_player = []
            page = riot.get_match_list(player['id'], region=region, champion_ids=champ['id'], ranked_queues='TEAM_BUILDER_DRAFT_RANKED_5x5', begin_time=last_week)
            while 'matches' in page.keys() and page['matches']:
                for m in page['matches']:
                    pprint(m)
                    if 'lane' not in m.keys():
                        print "Found a mysterious match list item:"
                        pprint(m)
                        continue
                    this_player.append({'lane': m['lane'], 'matchId': m['matchId'], 'region': m['region'], 'role': m['role']})
                if len(this_player) == page['totalGames']:
                    break
                time.sleep(1)
                print "NETWORK INNER - {}'s {} matches".format(player['name'], champ['name'])
                page = riot.get_match_list(player['id'], region=region, champion_ids=champ['id'], ranked_queues='TEAM_BUILDER_DRAFT_RANKED_5x5', begin_time=last_week, begin_index=page['endIndex'])
            if this_player:
                redis.hset('player_matches', "{}_{}".format(player['id'], champ['id']), json.dumps(this_player))
                matches += this_player
            time.sleep(2)

    if matches:
        redis.hset('matches', champ['id'], json.dumps(matches))

    return matches

if __name__ == "__main__":
    champions, items = get_static()
    players = get_players()
    print "{} players found".format(sum([len(y) for x,y in players.iteritems()]))

    matches = get_matches_for_champion(players, champions['Viktor'])
    print "Got {} Viktor matches".format(len(matches))
    print matches[0]