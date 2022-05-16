
from typing import Dict, List, Tuple, Callable
from numpy.typing import ArrayLike

import numpy as np
import pandas as pd

from numba import njit, typed, prange
from numba.core import types

# Numba constants have to be outside classes :(

# undirected edge constants
_UN_EDGE_SIZE = 3
_LL_UN_EDGE_POS = 2

# directed edge constants
_DI_EDGE_SIZE = _UN_EDGE_SIZE + 1
_LL_DI_EDGE_POS = 2

# generic constants
_EDGE_EMPTY_PTR = -1
_EDGE_BUFFER_FULL = -2
_EDGE_INVALID_INDEX = -3


################################
##  edge insertion functions  ##
################################

@njit
def _add_undirected_edge(buffer: np.ndarray, node2edge: np.ndarray, free_idx: int, src: int, tgt: int) -> int:
    """
    TODO: doc

    NOTE:
      - edges are added at the beginning of the linked list so we don't have to track its
        tail and the operation can be done in O(1). This might decrease cash hits because
        they're sorted in memory in the opposite direction we're iterating
    """

    if free_idx == _EDGE_EMPTY_PTR:
        return _EDGE_BUFFER_FULL

    elif free_idx < 0:
        return _EDGE_INVALID_INDEX
    
    next_edge = node2edge[src]
    node2edge[src] = free_idx

    buffer_index = free_idx * _UN_EDGE_SIZE
    next_empty = buffer[buffer_index + _LL_UN_EDGE_POS]

    buffer[buffer_index] = src
    buffer[buffer_index + 1] = tgt
    buffer[buffer_index + _LL_UN_EDGE_POS] = next_edge

    return next_empty


@njit
def _add_directed_edge(
    buffer: np.ndarray,
    node2src_edge: np.ndarray,
    node2tgt_edge: np.ndarray,
    free_idx: int,
    src: int,
    tgt: int,
) -> int:
    """
    TODO: doc

    NOTE:
      - see _add_undirected_edge note about cache misses.
    """

    if free_idx == _EDGE_EMPTY_PTR:
        return _EDGE_BUFFER_FULL

    elif free_idx < 0:
        return _EDGE_INVALID_INDEX
    
    next_src_edge = node2src_edge[src]
    next_tgt_edge = node2tgt_edge[tgt]
    node2src_edge[src] = free_idx
    node2tgt_edge[tgt] = free_idx

    buffer_index = free_idx * _DI_EDGE_SIZE
    next_empty = buffer[buffer_index + _LL_DI_EDGE_POS]

    buffer[buffer_index] = src
    buffer[buffer_index + 1] = tgt
    buffer[buffer_index + _LL_UN_EDGE_POS] = next_src_edge
    buffer[buffer_index + _LL_DI_EDGE_POS + 1] = next_tgt_edge

    return next_empty


@njit
def _add_undirected_edges(
    buffer: np.ndarray,
    edges: np.ndarray,
    empty_idx: int,
    n_edges: int,
    node2edge: np.ndarray
) -> Tuple[int, int]:

    # TODO: doc
    """
    Returns next empty index, -1 if full, -2 if there was some error
    """
    size = edges.shape[0]
    for i in range(size):

        # adding (u, v)
        if empty_idx == _EDGE_BUFFER_FULL:
            return _EDGE_BUFFER_FULL, n_edges
        empty_idx = _add_undirected_edge(buffer, node2edge, empty_idx, edges[i, 0], edges[i, 1])
        n_edges += 1

        # adding (v, u)
        if empty_idx == _EDGE_BUFFER_FULL:
            return _EDGE_BUFFER_FULL, n_edges
        empty_idx = _add_undirected_edge(buffer, node2edge, empty_idx, edges[i, 1], edges[i, 0])
        n_edges += 1

    return empty_idx, n_edges


@njit
def _add_directed_edges(
    buffer: np.ndarray,
    edges: np.ndarray,
    empty_idx: int,
    n_edges: int,
    node2src_edge: np.ndarray,
    node2tgt_edge: np.ndarray,
) -> Tuple[int, int]:
    # TODO: doc
    """
    Returns next empty index, -1 if full, -2 if there was some error
    """
    size = edges.shape[0]
    for i in range(size):

        if empty_idx == _EDGE_BUFFER_FULL:
            return _EDGE_BUFFER_FULL, n_edges

        empty_idx = _add_directed_edge(
            buffer, node2src_edge, node2tgt_edge, empty_idx, edges[i, 0], edges[i, 1]
        )
        n_edges += 1

    return empty_idx, n_edges


############################
## edge removal functions ##
############################

@njit(inline='always')
def _remove_edge(
    src_node: int,
    tgt_node: int,
    empty_idx: int,
    edges_buffer: np.ndarray,
    node2edges: np.ndarray,
    edge_size: int,
    ll_edge_pos: int,
) -> int:

    idx = node2edges[src_node]
    prev_buffer_idx = _EDGE_EMPTY_PTR

    while idx != _EDGE_EMPTY_PTR:
        buffer_idx = idx * edge_size
        next_edge_buffer_idx = edges_buffer[buffer_idx + ll_edge_pos]
        # edge found
        if edges_buffer[buffer_idx] == tgt_node:
            if prev_buffer_idx == _EDGE_EMPTY_PTR:
                node2edges[src_node] = idx
            else:
                edges_buffer[prev_buffer_idx + ll_edge_pos] = next_edge_buffer_idx
            edges_buffer[buffer_idx + ll_edge_pos] = empty_idx
            return idx
        prev_buffer_idx = buffer_idx
    
    return _EDGE_INVALID_INDEX


@njit
def _remove_undirected_edge(
    src_node: int,
    tgt_node: int,
    empty_idx: int,
    edges_buffer: np.ndarray,
    node2edges: np.ndarray,
) -> int:
    """TODO: doc"""

    empty_idx = _remove_edge(
        tgt_node, src_node, empty_idx, edges_buffer, node2edges, _UN_EDGE_SIZE, _LL_UN_EDGE_POS,
    )
    if empty_idx == _EDGE_INVALID_INDEX:
        return _EDGE_INVALID_INDEX

    empty_idx = _remove_edge(
        src_node, tgt_node, empty_idx, edges_buffer, node2edges, _UN_EDGE_SIZE, _LL_UN_EDGE_POS,
    )

    if empty_idx == _EDGE_INVALID_INDEX:
        return _EDGE_INVALID_INDEX

    return empty_idx


@njit
def _remove_directed_edge(
    src_node: int,
    tgt_node: int,
    empty_idx: int,
    node2src_edges: np.ndarray,
    node2tgt_edges: np.ndarray,
) -> int:

    info = _remove_edge(
        tgt_node, src_node, empty_idx, node2tgt_edges, _DI_EDGE_SIZE, _LL_DI_EDGE_POS + 1,
    )
    # empty index is not updated, just updating target linked list and buffer
    if info == _EDGE_INVALID_INDEX:
        return _EDGE_INVALID_INDEX

    empty_idx = _remove_edge(
        src_node, tgt_node, empty_idx, node2src_edges, _DI_EDGE_SIZE, _LL_DI_EDGE_POS,
    )
    if empty_idx == _EDGE_INVALID_INDEX:
        return _EDGE_INVALID_INDEX
    
    return empty_idx

    
#    # removing from target linked list first
#    idx = node2tgt_edges[tgt_node]
#    prev_buffer_idx = _EDGE_EMPTY_PTR
#
#    while idx != _EDGE_EMPTY_PTR:
#        buffer_idx = idx * _DI_EDGE_SIZE
#        # edge found
#        if edges_buffer[buffer_idx] == src_node:
#            # removing from linked list
#            next_edge_buffer_idx = edges_buffer[buffer_idx + _LL_DI_EDGE_POS + 1]
#            if prev_buffer_idx == _EDGE_EMPTY_PTR:
#                node2tgt_edges[tgt_node] = next_edge_buffer_idx
#            else:
#                edges_buffer[prev_buffer_idx + _LL_DI_EDGE_POS + 1] = next_edge_buffer_idx
#            break
#        prev_buffer_idx = buffer_idx
#
#    # removing from source linked list and updating empty
#    idx = node2src_edges[src_node]
#    prev_buffer_idx = _EDGE_EMPTY_PTR
#
#    while idx != _EDGE_EMPTY_PTR:
#        buffer_idx = idx * _DI_EDGE_SIZE
#        # edge found
#        if edges_buffer[buffer_idx + 1] == tgt_node:
#            # removing from linked list
#            next_edge_buffer_idx = edges_buffer[buffer_idx + _LL_DI_EDGE_POS]
#            if prev_buffer_idx == _EDGE_EMPTY_PTR:
#                node2src_edges[src_node] = next_edge_buffer_idx
#            else:
#                edges_buffer[prev_buffer_idx + _LL_DI_EDGE_POS] = next_edge_buffer_idx
#            # adding this node to start of the linked list and returning it
#            edges_buffer[buffer_idx + _LL_DI_EDGE_POS] = empty_idx
#            return idx
#        prev_buffer_idx = buffer_idx
#
#    return _EDGE_INVALID_INDEX


################################
##  edge iteration functions  ##
################################


@njit(inline='always')
def _iterate_edges(
    edge_ptr_indices: np.ndarray,
    edges_buffer: np.ndarray,
    edge_size: int,
    ll_edge_pos: int,
) -> typed.List:
    """TODO: doc"""
    edges_list = typed.List()

    for idx in edge_ptr_indices:
        edges = typed.List.empty_list(types.int64)
        edges_list.append(edges)

        while idx != _EDGE_EMPTY_PTR:
            buffer_idx = idx * edge_size
            edges.append(edges_buffer[buffer_idx])      # src
            edges.append(edges_buffer[buffer_idx + 1])  # tgt
            idx = edges_buffer[buffer_idx + ll_edge_pos]
    
    return edges_list


@njit
def _iterate_undirected_edges(edge_ptr_indices: np.ndarray, edges_buffer: np.ndarray) -> typed.List:
    return _iterate_edges(edge_ptr_indices, edges_buffer, _UN_EDGE_SIZE, _LL_UN_EDGE_POS)


@njit
def _iterate_directed_source_edges(edge_ptr_indices: np.ndarray, edges_buffer: np.ndarray) -> typed.List:
    return _iterate_edges(edge_ptr_indices, edges_buffer, _DI_EDGE_SIZE, _LL_DI_EDGE_POS)


@njit
def _iterate_directed_target_edges(edge_ptr_indices: np.ndarray, edges_buffer: np.ndarray) -> typed.List:
    return _iterate_edges(edge_ptr_indices, edges_buffer, _DI_EDGE_SIZE, _LL_DI_EDGE_POS + 1)


##############################
##  edge mapping functions  ##
##############################

@njit
def _create_world2buffer_map(world_idx: np.ndarray) -> typed.Dict:
    """
    Fills world indices to buffer indices mapping.
    """
    world2buffer = typed.Dict.empty(types.int64, types.int64)

    for i in range(world_idx.shape[0]):
        world2buffer[world_idx[i]] = i
    
    return world2buffer


@njit(parallel=True)  # TODO: benchmark if parallel is worth it
def _vmap_world2buffer(world2buffer: typed.Dict, world_idx: np.ndarray) -> typed.Dict:
    """
    Maps world indices to buffer indices.
    """
    buffer_idx = np.empty(world_idx.shape[0], dtype=types.int64)
    for i in prange(world_idx.shape[0]):
        buffer_idx[i] = world2buffer[world_idx[i]]
    return buffer_idx


class BaseGraph:
    # TODO: doc

    _NODE_EMPTY_PTR = -1

    # abstract constants
    _EDGE_DUPLICATION: int = ...
    _EDGE_SIZE: int = ...
    _LL_EDGE_POS: int = ...

    def __init__(self, n_nodes: int, ndim: int, n_edges: int):
        self._active = np.ones(n_nodes, dtype=bool)
        self._coords = np.zeros((n_nodes, ndim), dtype=np.float32)
        self._feats: Dict[str, np.ndarray] = {}

        self._empty_nodes: List[int] = []
        self._node2edges = np.full(n_nodes, fill_value=_EDGE_EMPTY_PTR, dtype=int)
        self._empty_edge_idx = 0 if n_edges > 0 else _EDGE_EMPTY_PTR
        self._n_edges = 0

        self._edges_buffer = np.full(n_edges * self._EDGE_DUPLICATION * self._EDGE_SIZE, fill_value=_EDGE_EMPTY_PTR, dtype=int)
        self._edges_buffer[self._LL_EDGE_POS : -self._EDGE_SIZE :self._EDGE_SIZE] = np.arange(1, self._EDGE_DUPLICATION * n_edges)

        self._world2buffer = typed.Dict.empty(types.int64, types.int64)
        self._buffer2world = np.full(n_nodes, fill_value=self._NODE_EMPTY_PTR, dtype=int)
    
    def init_nodes_from_dataframe(
        self,
        nodes_df: pd.DataFrame,
        coordinates_columns: List[str],
    ) -> None:
        # TODO: doc

        if nodes_df.index.dtype != np.int64:
            raise ValueError(f"Nodes indices must be int64. Found {nodes_df.index.dtype}.")
 
        n_nodes = len(nodes_df)

        if  n_nodes > self._coords.shape[0] or len(coordinates_columns) != self._coords.shape[1]:
            self._coords = nodes_df[coordinates_columns].values.astype(np.float32, copy=True)
            self._active = np.ones(n_nodes, dtype=bool)
            self._node2edges = np.full(n_nodes, fill_value=_EDGE_EMPTY_PTR, dtype=int)
            self._buffer2world = nodes_df.index.values.astype(np.uint64, copy=True)
            self._empty_nodes = []
        else:
            self._coords[:n_nodes] = nodes_df[coordinates_columns].values
            self._active.fill(True)
            self._node2edges.fill(_EDGE_EMPTY_PTR)
            self._buffer2world[:n_nodes] = nodes_df.index.values
            self._empty_nodes = list(reversed(range(n_nodes, len(self._active))))  # reversed so we add nodes to the end of it

        self._world2buffer = _create_world2buffer_map(self._buffer2world[:n_nodes])

        # NOTE:
        #  - feats and buffers arrays length may not match after this
        #  - feats should be indexed by their pandas DataFrame index (world index)
        self._feats = nodes_df.drop(coordinates_columns, axis=1)

    def add_node(self, index: int, coords: np.ndarray, features: Dict = {}) -> None:
        # TODO
        raise NotImplementedError
    
    def _realloc_edges_buffer(self, n_edges: int) -> None:
        # TODO: doc
        # augmenting size to match dummy edges
        n_edges = n_edges * self._EDGE_DUPLICATION
        old_n_allocated = self.n_allocated_edges * self._EDGE_DUPLICATION
        n_allocated = n_edges - old_n_allocated

        if n_allocated < 0:
            raise NotImplementedError("Edge buffer size decrease not implemented.")
        elif n_allocated == 0:
            raise ValueError("Tried to realloc to current buffer size.")

        old_buffer_size = len(self._edges_buffer)
        buffer_size = n_edges * self._EDGE_SIZE

        new_edges_buffer = np.full(buffer_size, fill_value=-1, dtype=int)
        new_edges_buffer[:len(self._edges_buffer)] = self._edges_buffer  # filling previous buffer data
        self._edges_buffer = new_edges_buffer

        # fills empty edges ptr
        self._edges_buffer[old_buffer_size + self._LL_EDGE_POS : -self._EDGE_SIZE :self._EDGE_SIZE] =\
             np.arange(old_n_allocated + 1, n_edges) 

        # appends existing empty edges linked list to the end of the new list
        self._edges_buffer[self._LL_EDGE_POS - self._EDGE_SIZE] = self._empty_edge_idx
        self._empty_edge_idx = old_n_allocated

    @property
    def n_allocated_edges(self) -> int:
        return len(self._edges_buffer) // (self._EDGE_DUPLICATION * self._EDGE_SIZE)

    @property
    def n_empty_edges(self) -> int:
        return self.n_allocated_edges - self.n_edges
    
    @property
    def n_edges(self) -> int:
        return self._n_edges

    def _validate_edges(self, edges: ArrayLike) -> np.ndarray:
        edges = np.atleast_2d(edges)

        if edges.ndim != 2:
            raise ValueError(f"Edges must be 1- or 2-dimensional. Found {edges.ndim}-dimensional.")
        
        if edges.shape[1] != 2:
            raise ValueError(f"Edges must be a sequence of length 2 arrays. Found length {edges.shape[1]}")

        return edges
    
    def _add_edges(self, edges: np.ndarray) -> None:
        """Abstract method, different implementation for undirected and directed graph."""
        raise NotImplementedError

    def add_edges(self, edges: ArrayLike) -> None:
        # TODO: 
        #   - doc
        #   - edges features
        edges = self._validate_edges(edges)

        if self.n_empty_edges < len(edges):
            self._realloc_edges_buffer(len(edges))

        self._add_edges(edges)
    
    def _remove_edges(self, edges: np.ndarray) -> None:
        raise NotImplementedError
    
    def remove_edges(self, edges: ArrayLike) -> None:
        # TODO: docs
        edges = self._validate_edges(edges)
        self._remove_edges(edges)
 
    def _map_world2buffer(self, world_idx: np.ndarray) -> np.ndarray:
        """Flattens the world indices buffer maps it to buffer coordinates and reshape back to original space."""
        shape = world_idx.shape
        buffer_idx = _vmap_world2buffer(self._world2buffer, world_idx.reshape(-1))
        return buffer_idx.reshape(shape)

    def _iterate_edges(
        self,
        node_indices: ArrayLike,
        node2edges: np.ndarray,
        iterate_edges_func: Callable[[np.ndarray, np.ndarray], List[np.ndarray]],
    ) -> List[np.ndarray]:
        """
        TODO: doc
        """
        node_indices = np.atleast_1d(node_indices)
        if node_indices.ndim > 1:
            raise ValueError

        flat_edges = iterate_edges_func(
            node2edges[self._map_world2buffer(node_indices)],
            self._edges_buffer,
        )
        return [
            self._buffer2world[e].reshape(-1, 2) if len(e) > 0 else np.empty((0,2))
            for e in flat_edges
        ]


class UndirectedGraph(BaseGraph):
    # TODO: doc

    _EDGE_DUPLICATION = 2
    _EDGE_SIZE = _UN_EDGE_SIZE
    _LL_EDGE_POS = _LL_UN_EDGE_POS

    def _add_edges(self, edges: np.ndarray) -> None:
        self._empty_edge_idx, self._n_edges = _add_undirected_edges(
            self._edges_buffer,
            edges,
            self._empty_edge_idx,
            self._n_edges,
            self._node2edges,
        )

    def edges(self, node_indices: ArrayLike) -> List[np.ndarray]:
        return self._iterate_edges(
            node_indices,
            node2edges=self._node2edges,
            iterate_edges_func=_iterate_undirected_edges,
        )
    
    def _remove_edges(self, edges: np.ndarray) -> None:
        return super()._remove_edges(edges)  # FIXME


class DirectedGraph(BaseGraph):
    # TODO: doc

    _EDGE_DUPLICATION = 1
    _EDGE_SIZE = _DI_EDGE_SIZE
    _LL_EDGE_POS = _LL_DI_EDGE_POS

    def __init__(self, n_nodes: int, ndim: int, n_edges: int):
        super().__init__(n_nodes, ndim, n_edges)
        self._node2tgt_edges = np.full(n_nodes, fill_value=_EDGE_EMPTY_PTR, dtype=int)

    def init_nodes_from_dataframe(
        self,
        nodes_df: pd.DataFrame,
        coordinates_columns: List[str],
    ) -> None:
        super().init_nodes_from_dataframe(nodes_df, coordinates_columns)
        n_nodes = len(nodes_df)
        if len(self._node2tgt_edges) < n_nodes:
            self._node2tgt_edges = np.full(n_nodes, fill_value=_EDGE_EMPTY_PTR, dtype=int)
        else:
            self._node2tgt_edges.fill(_EDGE_EMPTY_PTR)

    def _add_edges(self, edges: np.ndarray) -> None:
        self._empty_edge_idx, self._n_edges = _add_directed_edges(
            self._edges_buffer,
            edges,
            self._empty_edge_idx,
            self._n_edges,
            self._node2edges,
            self._node2tgt_edges,
        )
 
    def source_edges(self, node_indices: ArrayLike) -> List[np.ndarray]:
        return self._iterate_edges(
            node_indices,
            node2edges=self._node2edges,
            iterate_edges_func=_iterate_directed_source_edges,
        )

    def target_edges(self, node_indices: ArrayLike) -> List[np.ndarray]:
        return self._iterate_edges(
            node_indices,
            node2edges=self._node2tgt_edges,
            iterate_edges_func=_iterate_directed_target_edges,
        )

    def _remove_edges(self, edges: np.ndarray) -> None:
        return super()._remove_edges(edges)  # FIXME


# TODO:
#  - write remove edges test and expand it to removal of multiple edges in a single call