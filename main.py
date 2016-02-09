from riotwatcher import RiotWatcher, NORTH_AMERICA, KOREA, EUROPE_WEST
from datetime import datetime, timedelta
from pprint import pprint
import time
import shelve
import os

RIOT_API_KEY = os.environ.get('RIOT_API_KEY', '')
riot = RiotWatcher(RIOT_API_KEY)

shelf = shelve.open('cache')

def get_static():
    if shelf.has_key('champions') and shelf.has_key('items'):
        return shelf['champions'], shelf['items']

    champions = riot.static_get_champion_list()['data']
    items = riot.static_get_item_list()['data']
    shelf['champions'] = champions
    shelf['items'] = items
    return champions, items


def get_players():
    if shelf.has_key('players_by_region'):
        return shelf['players_by_region']
    players_by_region = {NORTH_AMERICA: [], KOREA: [], EUROPE_WEST: []}

    for region in players_by_region.keys():
        challengers = riot.get_challenger(region=region)
        masters = riot.get_master(region=region)
        for p in challengers['entries'] + masters['entries']:
            player = {'name': p['playerOrTeamName'], 'id': p['playerOrTeamId']}
            players_by_region[region].append(player)

    shelf['players_by_region'] = players_by_region
    return players_by_region


def get_matches_for_champion(players, champ):
    if shelf.has_key('matches_{}'.format(champ['id'])):
        shelf['matches_{}'.format(champ['id'])]

    matches = []

    last_week = int(time.mktime((datetime.utcnow() - timedelta(weeks=1)).timetuple()))
    for region in players.keys():
        for player in players[region]:
            this_player = []
            page = riot.get_match_list(player['id'], region=region, champion_ids=champ['id'], begin_time=last_week)
            while 'matches' in page.keys() and page['matches']:
                for m in page['matches']:
                    if 'lane' not in m.keys():
                        pprint(m)
                        break
                    this_player.append({'lane': m['lane'], 'matchId': m['matchId'], 'region': m['region'], 'role': m['role']})
                if len(this_player) == page['totalGames']:
                    break
                time.sleep(1)
                page = riot.get_match_list(player['id'], region=region, champion_ids=champ['id'], begin_time=last_week, begin_index=page['endIndex'])
            if this_player:
                matches += this_player
            time.sleep(2)
            

    shelf['matches_{}'.format(champ['id'])] = matches

    return matches

if __name__ == "__main__":
    champions, items = get_static()
    players = get_players()
    
    matches = get_matches_for_champion(players, champions['Viktor'])
    print len(matches)
    print matches[0]

    shelf.close()