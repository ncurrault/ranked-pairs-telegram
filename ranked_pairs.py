import copy

class Pair:
    def __init__(self, candidateA, candidateB):
        self.min_candidate = min(candidateA, candidateB)
        self.max_candidate = max(candidateA, candidateB)
        self.min_cand_votes = 0
        self.max_cand_votes = 0

    def process_ballot(self, ballot):
        if ballot[self.min_candidate] > ballot[self.max_candidate]:
            self.min_cand_votes += 1
        elif ballot[self.min_candidate] < ballot[self.max_candidate]:
            self.max_cand_votes += 1

    def get_winner(self):
        if self.min_cand_votes > self.max_cand_votes:
            return self.min_candidate
        elif self.min_cand_votes < self.max_cand_votes:
            return self.max_candidate
        else:
            return None

    def get_loser(self):
        if self.get_winner() == self.min_candidate:
            return self.max_candidate
        elif self.get_winner() == self.max_candidate:
            return self.min_candidate
        else:
            return None

    def get_winner_votes(self):
        return max(self.min_cand_votes, self.max_cand_votes)
    def get_loser_votes(self):
        return min(self.min_cand_votes, self.max_cand_votes)

    def __gt__(self, other):
        return self.get_winner_votes() > other.get_winner_votes() \
            or (self.get_winner_votes() == other.get_winner_votes() and \
            self.get_loser_votes() < other.get_loser_votes())
        # pair majority (Vxy) precedes another (Vzw) iff Vxy > Vzw
        # OR Vxy = Vzw and Vyx < Vwz
        # https://en.wikipedia.org/wiki/Ranked_pairs#Sort

def bfs(graph, source):
    """
    get connected component containing some source
    """
    to_explore = {source}
    visited = set()
    while len(to_explore) > 0:
        v = to_explore.pop()
        if v not in visited:
            to_explore.update(graph[v])
            visited.add(v)
    return visited

def creates_cycle(graph, source, destination):
    return source in bfs(graph, destination)

def get_sources(graph):
    sources = set(graph.keys())
    for losers in graph.values():
        sources -= losers
        # all of the nodes mentioned in these sets have in-degree >= 1
        # because there's an edge from some key to it
    return sources
    # sources have in-degree 0 by definition

def get_winners(ballots):
    """
    'ballots' should be a 2D array: rows are voters, columns are candidates,
    integer at [row][column] is the score this voter gave that candidate
    (the higher the better)
    """
    n_options = len(ballots[0])

    pairs = [ ]
    for a in range(n_options):
        for b in range(a):
            pairs.append(Pair(a, b))

    for pair in pairs:
        for ballot in ballots:
            pair.process_ballot(ballot)

    ranked_pairs = sorted(pairs, reverse=True) # roll credits!

    # candidate graph, as adjacency map
    graph = { n: set() for n in range(n_options) }
    for pair in ranked_pairs:
        winner, loser = pair.get_winner(), pair.get_loser()
        if (winner is not None) and not creates_cycle(graph, winner, loser):
            graph[winner].add(loser)

    return get_sources(graph)

def get_ranked_partitions(ballots):
    """
    'ballots' should be a 2D array: rows are voters, columns are candidates,
    integer at [row][column] is the score this voter gave that candidate
    (the higher the better)

    works by repeatedly calling get_winners, removing victors, and calling again
    until all candidates have won and been assigned a rank
    """
    n_options = len(ballots[0])
    ballots_copy = copy.deepcopy(ballots)

    already_won = set()
    result = []

    while True:
        winners = get_winners(ballots_copy)
        if len(winners.intersection(already_won)) > 0:
            break

        already_won.update(winners)
        result.append(winners)

        for w in winners:
            for ballot in ballots_copy:
                ballot[w] = -1
        # ensure this person is worse than abstain so they should never win until all other candidates have been picked

    assert len(already_won) == n_options
    return result

def get_candidate_rankings(ballots):
    """
    wrapper for get_ranked_partitions, returns results as a single list, where
    the integer at [i] represents the ranking of candidate [i] (1 being the best)
    """
    partitions = get_ranked_partitions(ballots)
    rankings = [ None for _ in ballots[0] ]

    rank = 1
    for part in partitions:
        for option_idx in part:
            rankings[option_idx] = rank
        rank += len(part)

    assert None not in rankings
    return rankings
