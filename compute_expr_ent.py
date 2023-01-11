# Compute the expressibility and entanglement capability metrics of a given circuit

from time import perf_counter
import numpy as np
import pandas as pd
import h5py
from itertools import combinations
import argparse
from typing import Tuple, List, Union
from qiskit.circuit import QuantumCircuit
from qiskit.quantum_info import Statevector
from triple_e import expressibility
from triple_e import entanglement_capability

from kernel_machines.terminal_enhancer import tcols
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning) # For pandas frame.append method

np.random.seed(42)


def main(args):
    circuit_list_expr_ent, circuit_labels = prepare_circs(args)
    data = None 
    if args["data_dependent"]: 
        data = get_data(args["data_path"])
    
    switcher = {
        "expr_ent_vs_circ": lambda: compute_expr_ent_vs_circuit(
            args, 
            circuit_list_expr_ent,
            circuit_labels, 
            data=data
        ),
        "expr_vs_qubits": lambda: expr_vs_nqubits(
            args=args,
            data=data
        )
    }
    df_results = switcher.get(args["compute"], lambda: None)()
    if df_results is None:
        raise TypeError(
            tcols.FAIL + "Given computation run does not exist!" + tcols.ENDC
        )
    # TODO variance of the kernel matrix vs. n_qubits (For exponential concentration)


def prepare_circs(args: dict) -> Tuple[List, List]:
    """Prepares the list of circuit needed for evaluation along with their names."""
    circuit_labels = ['NE_0', 'NE_1', 'L=1', 'L=2', 'L=3', 'L=4', 'L=5', 'L=6', 'FE']
    
    circuit_list_expr_ent = [lambda x, rep=rep: u_dense_encoding(x, nqubits=\
                             args["n_qubits"], reps=rep) for rep in range(1,7)]
    # Add the two no-entanglement circuits (NE_0, NE_1) at the beginning of the list
    circuit_list_expr_ent.insert(
        0,
        lambda x: u_dense_encoding_no_ent(x, nqubits=args["n_qubits"], reps=1, type=1)
    )
    circuit_list_expr_ent.insert(
        0,
        lambda x: u_dense_encoding_no_ent(x, nqubits=args["n_qubits"], reps=1, type=0)
    )
    # Add the full ent rep3 (FE)
    circuit_list_expr_ent.insert(
        -1,
        lambda x: u_dense_encoding_all(x, nqubits=args["n_qubits"], reps=3)
    )
    return circuit_list_expr_ent, circuit_labels


def compute_expr_ent_vs_circuit(args: dict, circuits: List[callable], 
                                circuit_labels: List[str], data: np.ndarray = None) \
-> pd.DataFrame:
    """
    Computes the expressibility and entanglement capability of a list of circuits, in 
    the conventional (uniformly sampled parameters from [0, 2pi]) and data-dependent manner.
    """
    print("\nComputing expressibility and entanglement capability of the circuits, "
          f"for {args['n_exp']} evaluations and n_shots = {args['n_shots']}." 
          f"\nCircuits: {circuit_labels}")

    n_params = 2*args["n_qubits"]
    df_expr_ent = pd.DataFrame(columns=['circuit', 'expr', 'expr_err', 
                               'ent', 'ent_err'])
    
    # Expr. and Ent. as a function of the circuit depth and amount of CNOT gates
    train_time_init = perf_counter()
    for i, circuit in enumerate(circuits):
        print(f"\nFor circuit {circuit_labels[i]}...")
        expr = []
        # Compute entanglement cap. only once, it fluctuates less than 0.1%
        # and does not require that high statistics
        if circuit_labels[i] in ['NE_0', 'NE_1']:
            val_ent = 0 # by construction
        else:
            val_ent = entanglement_capability(circuit, n_params, n_shots=10)
        
        for _ in range(args["n_exp"]):
            val_ex = expressibility(circuit, n_params, method='full', 
                                    n_shots=args['n_shots'], n_bins=75, data=data)
            expr.append(val_ex)
        expr = np.array(expr)
        ent = np.array(val_ent)
        print(f"expr = {np.mean(expr)} ± {np.std(expr)}")
        print(f"ent = {np.mean(ent)} ± {np.std(ent)}")
        
        d = {
            "circuit": circuit_labels[i],
            "expr": np.mean(expr),
            "expr_err": np.std(expr),
            "ent": np.mean(ent),
            "ent_err": np.std(ent),
        }
        df_expr_ent = df_expr_ent.append(d, ignore_index=True)
        
    train_time_fina = perf_counter()
    exec_time = train_time_fina - train_time_init
    print(
        "\nFull computation completed in: " + tcols.OKGREEN + f"{exec_time:.2e} sec. "
        f"or {exec_time/60:.2e} min. " + tcols.ENDC + tcols.SPARKS
    )
    print("\nResults: \n", df_expr_ent)
    df_expr_ent.to_csv(f"{args['out_path']}.csv")
    print(f"Saving in {args['out_path']}.csv " + tcols.ROCKET)
    return df_expr_ent


def expr_vs_nqubits(args: dict, rep: int = 3, n_exp: str = 20, 
                    data: Union[np.ndarray, List[np.ndarray]] = None)\
-> pd.DataFrame:
    """
    Computes the (data-dependent) expressibility of a data embedding circuit as a 
    function of the qubit number. Saves the output in a dataframe (.h5) with the 
    computed mean values and uncertainties.
    
    Args:
        data: List of the datasets available for n_qubits = 4, 8, 16 or None for 
              computation with uniformly sampled circuit parameters [0, 2pi].
    """
    print(f"Computing expressibility as a function of the qubit number, "
          f"for rep = {rep} of the data encoding circuit ansatz.")
    df_expr = pd.DataFrame(columns=['expr', 'expr_err'])
    n_qubits = range(1, 10)
    if data is not None:
        n_qubits = [4, 8, 16]

    train_time_init = perf_counter()
    for idx, n in enumerate(n_qubits):
        print(f"For n_qubits = {n}: ", end='')
        n_params = 2*n
        expr = []
        for _ in range(args["n_exp"]):
            val = expressibility(lambda x : u_dense_encoding(x, nqubits=n, reps=rep), 
                                 method="full", n_params=n_params, n_shots=args["n_shots"],
                                 n_bins=75, data=None if data is None else data[idx])
            expr.append(val)
        
        expr = np.array(expr)
        print(f"expr = {np.mean(expr)} ± {np.std(expr)}")
        d = {
            "expr": np.mean(expr),
            "expr_err": np.std(expr),
        }
        df_expr = df_expr.append(d, ignore_index=True)
    
    train_time_fina = perf_counter()
    exec_time = train_time_fina - train_time_init    
    print(
        "\nFull computation completed in: " + tcols.OKGREEN + f"{exec_time:.2e} sec. "
        f"or {exec_time/60:.2e} min. " + tcols.ENDC + tcols.SPARKS
    )
    print("\nResults: \n", df_expr)
    df_expr.to_csv(f"{args['out_path']}.csv")
    print(f"Saving in {args['out_path']}.csv " + tcols.ROCKET)
    return df_expr


def get_data(data_path: Union[str, List[str]], mult_qubits: bool = False) \
-> Tuple[np.ndarray]:
    """
    Loads the data, signal or background, given a path and returns the scaled to 
    (0, 2pi) numpy arrays.
    
    Args:
        data_path: Path to the .h5 dataset, or list of paths for multiple dataset 
                   loading.
        mult_qubits: If True the specified dataset (in data_path) is loaded for 
                     different qubit numbers, i.e., latent dimensions (4, 8, 16)
                     for the kernel machine training/testing.
    """
    print(tcols.BOLD + f"\nLoading the datasets: {data_path} " + tcols.ENDC)
    h5_data = [h5py.File(dataset_path, "r") for dataset_path in data_path]
    data = [np.asarray(h5_dataset.get("latent_space")) for h5_dataset in h5_data]
    data = [np.reshape(dataset, (len(dataset), -1)) for dataset in data]
    
    print(f"Loaded {len(data)} datasets array of shapes: ", end="")
    for dataset in data:
        print(f"{dataset.shape} ", end="")
        # rescaling to (0, 2pi) needed for the expr. and ent. computations.
        dataset *= np.pi
        dataset += np.pi
    print()
    
    if len(data) == 1: data = data[0]
    return data


def u_dense_encoding_no_ent(x, nqubits: int = 8, reps: int = 3, type: int = 0
) -> QuantumCircuit:
    """
    Constructs a feature map based on u_dense_encoding but removing entanglement.
    The 'type' argument corresponds the two No-Entanglement (NE) circuits in the paper.

    Args:
        nqubits: Int number of qubits used.

    Returns: The quantum circuit qiskit object used in the QSVM algorithm.
    """
    nfeatures = 2 * nqubits
    qc = QuantumCircuit(nqubits)
    for rep in range(reps):
        for feature, qubit in zip(range(0, nfeatures, 2), range(nqubits)):
            #qc.h(qubit)
            qc.u(np.pi / 2, x[feature], x[feature + 1], qubit)  # u2(φ,λ) = u(π/2,φ,λ)
        
        # Comment the below if only one layer is needed for the no entanglement test
        if type == 0: 
            for feature, qubit in zip(range(0, 2 * nqubits, 2), range(nqubits)):
                qc.u(x[feature], x[feature + 1], 0, qubit)
        
    return Statevector.from_instruction(qc)


def u_dense_encoding(x, nqubits=8, reps=1,):
    nfeatures = 2 * nqubits
    qc = QuantumCircuit(nqubits)
    for rep in range(reps):
        for feature, qubit in zip(range(0, nfeatures, 2), range(nqubits)):
            #qc.h(qubit)
            qc.u(np.pi / 2, x[feature], x[feature + 1], qubit)  # u2(φ,λ) = u(π/2,φ,λ)
        for i in range(nqubits):
            if i == nqubits - 1:
                break
            qc.cx(i, i + 1)

        for feature, qubit in zip(range(0, 2 * nqubits, 2), range(nqubits)):
            qc.u(x[feature], x[feature + 1], 0, qubit)
    return Statevector.from_instruction(qc)


def u_dense_encoding_all(x, nqubits: int = 8, reps: int = 3) -> QuantumCircuit:
    """
    Constructs a feature map, inspired by the dense encoding and data
    re-uploading methods.

    Args:
        nqubits: Int number of qubits used.

    Returns: The quantum circuit qiskit object used in the QSVM algorithm.
    """
    nfeatures = 2 * nqubits
    qc = QuantumCircuit(nqubits)
    for rep in range(reps):
        for feature, qubit in zip(range(0, nfeatures, 2), range(nqubits)):
            #qc.h(qubit)
            qc.u(np.pi / 2, x[feature], x[feature + 1], qubit)  # u2(φ,λ) = u(π/2,φ,λ)
        
        for qpair in list(combinations(range(nqubits), 2)):
            qc.cx(qpair[0], qpair[1])

        for feature, qubit in zip(range(0, 2 * nqubits, 2), range(nqubits)):
            qc.u(x[feature], x[feature + 1], 0, qubit)
    return Statevector.from_instruction(qc)


def get_arguments() -> dict:
    """
    Parses command line arguments and gives back a dictionary.
    Returns: Dictionary with the arguments
    """
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "--n_qubits",
        type=int,
        default=8,
        help="Number of qubits for feature map circuit.",
    )
    parser.add_argument(
        "--n_shots",
        type=int,
        required=True,
        help="How many fidelity samples to generate per expressibility and entanglement "
             "capability evaluation.",
    )
    parser.add_argument(
        "--n_exp",
        type=int,
        required=True,
        help="Number of evaluations ('experiments') of the expressibility and " 
             "entanglement capability. To estimate the mean and std of around " 
             "the true value",
    )
    parser.add_argument(
        "--out_path",
        type=str,
        required=True,
        help="Output dataframe to be used for plotting.",
    )
    parser.add_argument(
        "--data_path",
        nargs="+",
        help="Path to signal dataset (background or signal .h5 file) to be used in "
             "expr. calculation. Multiple datasets can also be given for the `expr_vs_qubit` "
             "data-dependent computation." ,
    )
    parser.add_argument(
        "--compute",
        type=str,
        required=True,
        choices=["expr_ent_vs_circ", "expr_vs_qubits", "var_kernel_vs_circ"],
        help="Run different calculations: compute expressibility and entanglement "
        "capability of different circuits, compute expressibility as a function of the "
        "number of qubits, and TODO",
    )
    parser.add_argument(
        "--data_dependent",
        action="store_true",
        help="Compute the expressibility as a data-dependent quantity",
    )
    args = parser.parse_args()
    args = {
        "n_qubits": args.n_qubits,
        "n_shots": args.n_shots,
        "n_exp": args.n_exp,
        "out_path": args.out_path,
        "data_path": args.data_path,
        "compute": args.compute,
        "data_dependent": args.data_dependent,
    }

    return args

if __name__ == "__main__":
    args = get_arguments()
    main(args)
