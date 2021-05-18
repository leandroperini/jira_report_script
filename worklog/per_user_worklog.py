#!/usr/bin/python3
import csv
import json
from datetime import datetime
from math import floor
from pathlib import Path

import jmespath
import requests
from dateutil.parser import parse

p = Path(__file__).with_name('config.json')
f = open(p)
configs = json.load(f)
user = configs['user']
passwd = configs['password']
board = configs['board_id']
period_start = datetime.strptime(configs['period']['start'], '%Y-%m-%d')
period_end = datetime.strptime(configs['period']['end'], '%Y-%m-%d')

jira_url = configs['jira_url']
members_to_analyse = configs['members_to_analyse']
monitored_statuses = configs['status_to_analyse']

assignees = "'" + "', '".join(members_to_analyse) + "'"
status_url = 'rest/api/2/search?maxResults=1000&fields=changelog&expand=changelog&jql=assignee in ({assignees}) and (created >= "{period_start}" and created <= "{period_end}" or updated >= "{period_start}" and updated <= "{period_end}" or resolved >= "{period_start}" and resolved <= "{period_end}")  and ( issueFunction in issuesInEpics("\'Parent Link\' = \'OMNI-29757\' or \'Account\' = \'OMNI-29757\' ") or Account = "OMNI-29757")'.format(assignees=assignees, period_start=period_start.strftime('%Y/%m/%d 00:00'), period_end=period_end.strftime('%Y/%m/%d 23:59'))
print(status_url)
try:
    r = requests.get(jira_url + status_url, auth=(user, passwd))
    issues = jmespath.search("issues[].{key:key, changes:changelog.histories[?not_null(items[?fromString != toString && field == 'status'])].{author: author.name, date:created, from:items[?fromString != toString && field == 'status'] | @[0].fromString, to:items[?fromString != toString && field == 'status'] | @[0].toString} | sort_by(@, &date) } | @[?not_null(changes)]", r.json())
except Exception as e:
    print('Some unexpected error (code:' + str(r.status_code) + ') occurred while getting issues: ' + str(e))

worklog = {}
for issue in issues:
    previous = 0
    for idx, change in enumerate(issue['changes']):
        work_time = ''
        prev_change = issue['changes'][previous]
        if prev_change['author'] not in members_to_analyse:
            previous = idx
            continue
        if prev_change['author'] not in worklog:
            worklog[prev_change['author']] = {}
        if issue['key'] not in worklog[prev_change['author']]:
            worklog[prev_change['author']][issue['key']] = []

        if str.upper(change['from']) in monitored_statuses:
            print('Issue {issue} Matched-> {idx}'.format(issue=issue['key'], idx=idx))

            curr_date = parse(change['date'])
            prev_date = parse(prev_change['date'])

            work_time = floor((curr_date - prev_date).total_seconds())

            days = floor(work_time / (3600 * 24))
            hours = floor(work_time / 3600) - (days * 24)
            minutes = floor(work_time / 60) - (days * 24 * 60) - (hours * 60)
            work_time = (str(days) + 'd ' if days > 0 else '') + (str(hours) + 'h ' if hours > 0 else '') + (str(minutes) + 'm ' if minutes > 0 else '')

            worklog[prev_change['author']][issue['key']].append({
                "issue":           issue['key'],
                "workTimeSeconds": work_time,
                "workTime":        work_time.strip(),
                "from":            change['from'],
                "to":              change['to'],
                "startedAt":       prev_change['date'],
                "endedAt":         change['date'],
            })
        previous = idx
        if len(worklog[prev_change['author']][issue['key']]) == 0 or len(work_time) == 0:
            del worklog[prev_change['author']][issue['key']]
        if len(worklog[prev_change['author']]) == 0:
            del worklog[prev_change['author']]

for member, member_worklog in worklog.items():
    member_cleaned = member.replace('.', '_')
    print('Writing csv file: {0}_worklog.csv'.format(member_cleaned))
    csv_f = open('reports\{member_name}_worklog.csv'.format(member_name=member_cleaned), 'w')
    csv_writer = csv.writer(csv_f)
    is_header = True
    for issue, issue_worklog in member_worklog.items():
        for worklog_data in issue_worklog:
            print(worklog_data)
            if is_header:
                header = worklog_data.keys()
                csv_writer.writerow(header)
                is_header = False
            csv_writer.writerow(worklog_data.values())

    csv_f.close()
