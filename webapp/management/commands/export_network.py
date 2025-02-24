from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.models import Channel

import networkx as nx
from fa2 import ForceAtlas2


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args, **options):
        graph = nx.DiGraph()
        for u in Channel.objects.filter(organization__is_interesting=True):
            graph.add_node(u.pk, data=u.network_data)

        edge_list = []
        for u in Channel.objects.filter(organization__is_interesting=True):
            for w in Channel.objects.filter(organization__is_interesting=True).exclude(id=u.id):
                count = w.message_set.all().count()
                weight = (
                    0
                    if not count
                    else (
                        w.message_set.filter(forwarded_from=u).count()
                        + u.reference_message_set.filter(channel=w).count()
                    )
                    / count
                )
                if weight > 0:
                    edge_list.append([w.pk, u.pk, weight])

        max_weight = max([e[-1] for e in edge_list])
        for edge in edge_list:
            graph.add_edge(edge[0], edge[1], weight=max(10 * edge[2] / max_weight, 0.0001))

        forceatlas2 = ForceAtlas2(
            # Behavior alternatives
            outboundAttractionDistribution=True,  # Dissuade hubs
            edgeWeightInfluence=1.0,
            # Performance
            jitterTolerance=1.0,  # Tolerance
            barnesHutOptimize=True,
            barnesHutTheta=1.2,
            # Tuning
            scalingRatio=2.0,
            strongGravityMode=False,
            gravity=1.0,
            # Log
            verbose=False,
        )

        positions = forceatlas2.forceatlas2_networkx_layout(graph, pos=None, iterations=settings.FA2_ITERATIONS)
        print(positions)
