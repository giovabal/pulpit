import json
from datetime import datetime

from django.core.management.base import BaseCommand

from webapp.models import Channel

date_limit = datetime(2022, 11, 1)


def clean_name(s):
    s = str(s)
    if not s:
        return s

    if s.startswith("'"):
        s = s[1:]

    return s.replace(",", "").replace('"', "")


def node_row(u):
    row_data = [
        f'"{u.telegram_id}"',
        clean_name(u.username or u.telegram_id),
        clean_name(u.title or u.telegram_id),
        u.organization,
        u.participants_count or 0,
        u.message_set.count() or 0,
        "channel" if u.broadcast else "group",
    ]
    return ",".join(map(str, row_data)) + "\n"


def edge_row(p, k, w):
    return '"' + str(p.telegram_id) + '","' + str(k.telegram_id) + '",true,' + str(w) + "\n"


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args, **options):
        print("Saving all data")
        data = {}
        filename = "tm_data_archive.json"
        with open(filename, "w") as outputfile:
            for u in Channel.objects.filter(date__lt=date_limit):
                data[u.telegram_id] = {
                    "group": u.organization,
                    "type": u.organization_type,
                    "is_interesting": u.is_interesting,
                }
            outputfile.write(json.dumps(data))

        print("Exporting all data, full relationships")
        node_header = "nodedef>name VARCHAR, link VARCHAR, title VARCHAR, group VARCHAR, participants INTEGER, messages INTEGER, type VARCHAR\n"
        edge_header = "edgedef>node1 VARCHAR, node2 VARCHAR, directed BOOLEAN, weight DOUBLE\n"
        filename = "tm_export_all_fr.gdf"
        node_list = []
        for u in Channel.objects.filter(is_interesting=True, date__lt=date_limit):
            node_list.append(u)

        edge_list = []
        for u in Channel.objects.filter(is_interesting=True, date__lt=date_limit):
            for w in Channel.objects.filter(is_interesting=True, date__lt=date_limit).exclude(id=u.id):
                relation_messages = (
                    0
                    if not w.message_set.filter(date__lt=date_limit).count()
                    else (
                        w.message_set.filter(forwarded_from=u, date__lt=date_limit).count()
                        + u.reference_message_set.filter(channel=w, date__lt=date_limit).count()
                    )
                    / w.message_set.filter(date__lt=date_limit).count()
                )
                if relation_messages > 0:
                    edge_list.append([w, u, relation_messages])

        max_weight = max([e[-1] for e in edge_list])
        edge_list = [e[0:-1] + [max(10 * e[-1] / max_weight, 0.0001)] for e in edge_list]
        with open(filename, "w") as outputfile:
            outputfile.write(node_header)
            for row in node_list:
                outputfile.write(node_row(row))

            outputfile.write(edge_header)
            for row in edge_list:
                outputfile.write(edge_row(*row))
