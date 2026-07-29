"""
Algorithm Helper Module for La Forge
=====================================
Indexes optimized data structures and algorithms templates based on
TheAlgorithms repository (https://github.com/thealgorithms) to allow
dynamic developer agents to retrieve and inject clean implementations.

NMP: TOOL|INDEX|algorithm_helper|savings=70|pattern=algorithms template database|approach=Standard optimized python implementations catalog
"""

from typing import Dict, Any, Optional, List

ALGORITHM_TEMPLATES = {
    "search": {
        "binary_search": {
            "name": "Binary Search",
            "complexity": "O(log n)",
            "code": """def binary_search(arr: list, target) -> int:
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1"""
        }
    },
    "sort": {
        "quicksort": {
            "name": "Quick Sort",
            "complexity": "O(n log n)",
            "code": """def quicksort(arr: list) -> list:
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)"""
        }
    },
    "graph": {
        "dijkstra": {
            "name": "Dijkstra's Pathfinding",
            "complexity": "O((V + E) log V)",
            "code": """import heapq

def dijkstra(graph: dict, start) -> dict:
    distances = {node: float('inf') for node in graph}
    distances[start] = 0
    pq = [(0, start)]
    
    while pq:
        curr_dist, curr_node = heapq.heappop(pq)
        
        if curr_dist > distances[curr_node]:
            continue
            
        for neighbor, weight in graph[curr_node].items():
            distance = curr_dist + weight
            if distance < distances[neighbor]:
                distances[neighbor] = distance
                heapq.heappush(pq, (distance, neighbor))
                
    return distances"""
        }
    },
    "compression": {
        "huffman": {
            "name": "Huffman Coding Nodes",
            "complexity": "O(n log n)",
            "code": """import heapq
from collections import Counter

class HuffmanNode:
    def __init__(self, char, freq):
        self.char = char
        self.freq = freq
        self.left = None
        self.right = None

    def __lt__(self, other):
        return self.freq < other.freq

def build_huffman_tree(text: str) -> Optional[HuffmanNode]:
    if not text:
        return None
    counter = Counter(text)
    heap = [HuffmanNode(char, freq) for char, freq in counter.items()]
    heapq.heapify(heap)
    
    while len(heap) > 1:
        node1 = heapq.heappop(heap)
        node2 = heapq.heappop(heap)
        merged = HuffmanNode(None, node1.freq + node2.freq)
        merged.left = node1
        merged.right = node2
        heapq.heappush(heap, merged)
        
    return heap[0]"""
        }
    }
}


def get_algorithm_template(category: str, name: str) -> Optional[Dict[str, str]]:
    """Retrieve algorithm implementation details and code."""
    cat = ALGORITHM_TEMPLATES.get(category.lower())
    if cat:
        return cat.get(name.lower())
    return None


def list_categories() -> List[str]:
    """List all available algorithm categories."""
    return list(ALGORITHM_TEMPLATES.keys())


def list_algorithms_in_category(category: str) -> List[str]:
    """List all algorithms indexed under a category."""
    cat = ALGORITHM_TEMPLATES.get(category.lower())
    if cat:
        return list(cat.keys())
    return []
