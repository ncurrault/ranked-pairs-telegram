import sys
import csv

def ballotToInt(ballot):
    for voter in range(len(ballot)):
        for cand in range(len(ballot[voter])):
            try:
                ballot[voter][cand] = int(ballot[voter][cand].strip(' \'[]'))
            except ValueError:
                ballot[voter][cand] = 0


def makesCycle(newEdge, graph, visited):
    '''
    recursively checks if adding a directed edge to a graph would create a cycle

    inputs:
        newEdge: a list of the vertices to be connected. The 0th element is
        where the edge is coming from.
        graph: the graph to check. It is assumed to be acyclic. Represented as a
            dictionary of sets
        visited: a set containing the edges that have been visited so far

    returns:
        a bool that is True iff adding the edge creates a cycle
    '''
    # terminate recursion early in case of cycle
    if newEdge[0] in visited or newEdge[1] in visited:
        return True
    # add current node to visited set
    newVisit = visited | set([newEdge[0]])
    # recurse through the graph
    result = False
    for node in graph[(newEdge[1])]:
        result |= makesCycle([newEdge[1], node], graph, newVisit)
    return result

def findRoots(graph):
    '''
    finds the roots of a graph

    inputs:
        graph: the graph, represented as a dictionary of sets

    returns:
        a set of all of the roots of the graph
    '''
    rootSet = set(graph.keys())
    nonRoot = set([])
    for sets in graph.values():
        nonRoot |= sets
    rootSet = rootSet - nonRoot
    return rootSet

def makeGraph(pairs, nodes):
    '''
    constructs the acyclic graph from an ordered listing of pairwise results

    inputs:
        pairs: a list of tuples, which represent the pairwise results, the
            winner is the first value
        nodes: a set of all candidates

    returns:
        the graph represented as a dictionary of sets
    '''
    graph = {}
    # populate the graph with nodes
    for node in nodes:
        graph[node] = set([])
    # populate the graph with edges
    for pair in pairs:
        if (not makesCycle(pair, graph, set([]))) and pair[2] != 0:
            graph[pair[0]] = graph[pair[0]] | set([pair[1]])
    return graph

def partition(dataList, low, high):
    '''
    partition function for inplace quicksort

    inputs:
        dataList: a list of 4 tuples, the first element being the winner, second
            the loser third the margin of victory, and 4th the votes for loser
        low: the low index in the list
        high: the hiogh index in the list

    returns:
        the index of the pivot
    '''
    pivot = dataList[high]
    i = low - 1
    for j in range(low, high):
        if dataList[j][2] > pivot[2] or (dataList[j][2] == pivot[2] and dataList[j][3] < pivot[3]):
            i += 1
            temp = dataList[i]
            dataList[i] = dataList[j]
            dataList[j] = temp
    dataList[high] = dataList[i + 1]
    dataList[i + 1] = pivot
    return i + 1


def quicksort(dataList, low, high):
    '''
    typical inplace quicksort alogrithm, but made for the data being 4-tuples

    inputs:
        dataList: a list of 4 tuples, the first element being the winner, second
            the loser third the margin of victory, and 4th the votes for loser
        low: the low index in the list
        high: the high index in the list

    returns:
        nothing, but the dataList is sorted in the process
    '''
    if low < high:
        index = partition(dataList, low, high)
        quicksort(dataList, low, index - 1)
        quicksort(dataList, index + 1, high)

def sortPairs(voteData):
    '''
    uses quicksort to sort pairs by margin of victory, with number of votes for
    the losing candidate as the tiebreaker

    inputs:
        voteData: a dictionary of dictionaires of ints reprensting the number of
            people preferring the first key over the second key
    returns:
        a sorted list of 4-tuples, the first element being the winner, second
        the loser third the margin of victory, and 4th the votes for loser
    '''

    quicksort(voteData, 0, len(voteData) -1)
    return voteData


class Votes:
    '''
    a data structure to represent the raw and processed vote data
    '''
    def __init__(self):
        self.candSet = set([])
        self.voteData = {}
        self.graph = {}
        self.pairs = []
        self.sortedPairs = []
        self.victor = ""
        self.errorLog = []
    def findVictor(self):
        '''
        determines who won the election from the list of pairs

        object changes:
            if self.pairs is nonempty, sets self.graph to be the corresponding
            graph, as well as self.victor to be the winner of the election

        error handling:
            if self.pairs is empty, raises ValueError
        '''
        if self.sortedPairs == []:
            raise ValueError
        self.graph = makeGraph(self.sortedPairs, self.candSet)
        rootSet = findRoots(self.graph)
        if len(rootSet) == 1:
            self.victor = str(rootSet)
        else:
            self.victor = "Tie"

    def orderPairs(self):
        self.sortedPairs = sortPairs(self.pairs)

    def createPairs(self):
        '''
        creates the pairwise comparisons from the raw vote data

        object changes:
            if self.voteData is nonempty, sets self.pairs to be an unsorted list
            of pairwise polling results between candidates in self.CandSet.
            There will be 2 entries for each pair.

        error handling:
            if self.voteData is empty or self.candSet is empty, raises ValueError
        '''
        if not self.voteData or not self.candSet:
            raise ValueError
        for person in self.candSet:
            for opponent in self.candSet:
                if person != opponent:
                    try:
                        score = self.voteData[person][opponent]
                        oppScore = self.voteData[opponent][person]
                        if score > oppScore:
                            self.pairs.append([person, opponent, score - oppScore, oppScore])
                        elif score == oppScore:
                            msg = score + " People voted for both "+person+" and "+opponent
                            self.errorLog.append(msg)
                    except:
                        msg = "No comparison in data between "+person+" and "+opponent
                        self.errorLog.append(msg)

    def importData(self, rawData, header):
        for person in header:
            self.voteData[person] = {}
            for opponent in header:
                self.voteData[person][opponent] = 0
        ballotToInt(rawData)
        for voter in range(len(rawData)):
            for person in range(len(rawData[voter])):
                for opponent in range(len(rawData[voter])):
                    if rawData[voter][person] > rawData[voter][opponent]:
                        self.voteData[header[person]][header[opponent]] += 1
                    elif rawData[voter][person] < rawData[voter][opponent]:
                        continue
                    elif rawData[voter][person] != 0:
                        self.voteData[header[person]][header[opponent]] += 1

    def importCand(self, candList):
        self.candSet = set(candList)

    def report(self, filename):
        with open(filename, 'w') as log:
            log.write("List of candidates:\n\n")
            for person in self.candSet:
                log.write(person + "\n")
            log.write("\n\nPairs in order, with margin of victory and votes for loser:\n\n")
            for pair in self.sortedPairs:
                log.write(str(pair) + "\n")
            log.write("\n\nPotential Errors:\n\n")
            for line in self.errorLog:
                log.write(line + "\n")
            log.write("\n\n\nWinner:\n" + self.victor)

    def process(self, rawData, header, candList, file=""):
        self.importData(rawData, header)
        self.importCand(candList)
        self.createPairs()
        self.orderPairs()
        self.findVictor()
        if file != "":
            self.report(file)
        else:
            print(self.victor)




if __name__ == "__main__":
    try:
        votes = sys.argv[1]
        candidates = sys.argv[2]
    except:
        print("usage:\ncountVotes.py voteData CandList [--file filename]")
        exit(2)
    if len(sys.argv) == 5:
        filename = sys.argv[4]
    else:
        filename = ""
    with open(votes, 'r') as votecsv:
        header = votecsv.readline()
        header = header.strip().split(',')
        for i in range(len(header)):
            header[i] = header[i].strip()
        data = votecsv.readline()
        data = [data.strip().split(',')]
        line = votecsv.readline()
        line = line.strip().split(',')
        while line != ['']:
            data.append(line)
            line = votecsv.readline()
            line = line.strip().split(',')
    with open(candidates, 'r') as cand:
        candList = cand.readline()
        candList = candList.strip().split(',')
        for i in range(len(candList)):
            candList[i] = candList[i].strip()
    election = Votes()
    election.process(data,header,candList,filename)
