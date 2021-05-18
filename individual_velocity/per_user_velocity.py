#!/usr/bin/python3
import csv
import json
from datetime import datetime, timedelta
from math import ceil

import jmespath
import requests
from dateutil.parser import parse

f = open('config.json')
configs = json.load(f)
user = configs['user']
passwd = configs['password']
board = configs['board_id']
period = configs['period_months']
jira_url = configs['jira_url']
members_to_analyse = configs['members_to_analyse']

try:
    r = requests.get(jira_url + 'rest/agile/latest/board/' + board + '/sprint?state=closed,active&maxResults=1000', auth=(user, passwd))
    sprints = jmespath.search('values[].{id: id, name: name, completed_at: completeDate, ends_at: endDate}', r.json())
except Exception as e:
    print('Some unexpected error (code:' + str(r.status_code) + ') occurred while getting sprints: ' + str(e))

past_months = datetime.now() - timedelta(weeks=period * 4)

per_sprint_issues_points = {}
cache = {}
for member_name in members_to_analyse:
    print('Processing data for member: ' + member_name)
    for sprint in sprints:
        sprint_analysis = {}

        completed_at = parse(sprint['completed_at'] if sprint['completed_at'] is not None else sprint['ends_at']).date()

        if completed_at < past_months.date():
            continue

        print('Checking sprint ' + sprint['name'] + ' completed at ' + completed_at.isoformat())
        sprint_url = "rest/agile/latest/board/{board}/sprint/{sprint}/issue?jql=type not in ('Sub-tarefa')&maxResults=1000".format(board=board, sprint=sprint['id'])
        print(jira_url + sprint_url, end=' ')

        cache_key = str(sprint['id']) + str(board)
        if cache_key not in cache:
            retries = 0
            r.status_code = 0
            while retries <= 3 and str(r.status_code) != '200':
                r = requests.get(jira_url + sprint_url, auth=(user, passwd))
                print('http -> ' + str(r.status_code))
                retries += 1
            cache[cache_key] = r.json()
        else:
            print('From cache')

        team_members = jmespath.search('issues[?fields.status.name==\'Done\' && fields.resolution.name==\'Concluída\'].fields[].assignee.name', cache[cache_key])
        team_members = list(dict.fromkeys(team_members))

        team_points_average_without_me = 0
        team_points_average_with_me = 0

        for member in team_members:
            team_points_average_with_me += jmespath.search('issues[?fields.assignee.name==\'' + member + '\' && fields.status.name==\'Done\' && fields.resolution.name==\'Concluída\'].fields[].customfield_10106 | @ || [`0`] | ceil(sum(@))', cache[cache_key])
            if member == member_name:
                continue
            team_points_average_without_me += jmespath.search('issues[?fields.assignee.name==\'' + member + '\' && fields.status.name==\'Done\' && fields.resolution.name==\'Concluída\'].fields[].customfield_10106 | @ || [`0`] | ceil(sum(@))', cache[cache_key])

        team_points_average_without_me = ceil(team_points_average_without_me / (len(team_members) - 1))
        team_points_average_with_me = ceil(team_points_average_with_me / len(team_members))

        total_sprint_points = jmespath.search('issues[].fields[].customfield_10106 | @ || [`0`] | {total_sprint_points:ceil(sum(@))}', cache[cache_key])
        team_contribution_average = ceil((team_points_average_without_me * 100) / total_sprint_points['total_sprint_points'])

        member_analysis = jmespath.search('issues[?fields.assignee.name==\'' + member_name + '\' && fields.status.name==\'Done\' && fields.resolution.name==\'Concluída\'].fields[].customfield_10106 | @ || [`0`] | {my_points: ceil(sum(@)), hardest: ceil(max(@)), easiest: ceil(min(@))}', cache[cache_key])

        sprint_analysis[sprint['name']] = {
            "sprint":                    sprint['name'], **member_analysis,
            "team_points_average-without_me":       team_points_average_without_me,
            "team_points_average-with_me":       team_points_average_with_me,
            **total_sprint_points,
            "my_contribution":           '{0}%'.format(str(ceil((member_analysis['my_points'] * 100) / total_sprint_points['total_sprint_points']))),
            "team_contribution_average": '{0}%'.format(str(team_contribution_average)),
            "team_size":                 len(team_members),
        }
        per_sprint_issues_points.update(sprint_analysis)

    period_average = jmespath.search('@.*.my_points | avg(@)', per_sprint_issues_points)
    team_period_average_without_me = jmespath.search('@.*."team_points_average-without_me" | avg(@)', per_sprint_issues_points)
    team_period_average_with_me = jmespath.search('@.*."team_points_average-with_me" | avg(@)', per_sprint_issues_points)

    print('Writing csv file: {0}_velocity.csv'.format(member_name))
    csv_f = open('reports/' + member_name + '_velocity.csv', 'w')
    csv_writer = csv.writer(csv_f)
    is_header = True
    for sprint_name, sprint in per_sprint_issues_points.items():
        sprint.update({
            "my_period_average":   ceil(period_average),
            "team_period_average-without_me": ceil(team_period_average_without_me),
            "team_period_average-with_me": ceil(team_period_average_with_me)
        })
        print(sprint)
        if is_header:
            header = sprint.keys()
            csv_writer.writerow(header)
            is_header = False
        csv_writer.writerow(sprint.values())

    csv_f.close()
