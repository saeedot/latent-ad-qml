# Assessing the model performance using k-fold testing. The test dataset is
# comprised of background (QCD) data and unseen anomalies (new-physics) data.

from time import perf_counter
import numpy as np
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
import qad.algorithms.kernel_machines.util as util
import qad.algorithms.kernel_machines.backend_config as bc
import qad.algorithms.kernel_machines.data_processing as data_processing
from qad.algorithms.kernel_machines.terminal_enhancer import tcols
from qiskit_machine_learning.kernels import QuantumKernel

from qad.algorithms.kernel_machines.one_class_qsvm import OneClassQSVM

def get_scores(model, data):
    return model.decision_function(data)

def main(args: dict):
    """Asesses the performance of the trained models using k-fold testing.
    The test dataset is comprised of background (QCD) data and unseen during
    training, anomalous (new-physics) data.

    If the chosen model is tested on hardware, then only 1 fold is computed.

    Parameters
    ----------
    args : dict
        Configuration dictionary, with the following arguments.
    sig_path: str
        Path to the signal/anomaly dataset (.h5 format).
    bkg_path: str
        Path to the QCD background dataset (.h5 format).
    test_bkg_path: str
        Path to the background testing dataset (.h5 format).
    model: str
        The folder path of the QSVM model.
    ntest: int
        The number of the testing events required for a crosscheck.
    kfolds: int
        Number of k-validation/test folds used.
    mod_quantum_instance: bool
        Reconfigure the quantum " "instance and backend.
    unsup: bool
        Flag to choose between unsupervised and supervised models.
    config_file: str
        Private configuration file for IBMQ API token
    """
    _, test_loader = data_processing.get_data(args)
    test_features, test_labels = data_processing.shuffle_data(test_loader[0], test_loader[1])
    sig_fold, bkg_fold = data_processing.get_kfold_data(
        test_features, test_labels, args["kfolds"]
    )
    output_path = args["model"]
    model = util.load_model(output_path + "model")
    initial_layout = [5, 8, 11, 14, 13, 12, 10, 7]
    seed = 12345
    if args["config_file"] is not None:
        with open(args["config_file"]) as pconfig:
            private_configuration = json.load(pconfig)
            ibmq_config = private_configuration["IBMQ"]
    else:
        ibmq_config = None

    print("Computing model scores... ", end="")
    scores_time_init = perf_counter()

    if args["kfolds"] == 1:
        print("Only one fold...")
        if args["mod_quantum_instance"]:
            model._backend_config = {
                "optimization_level": 3,
                "initial_layout": initial_layout,
                "seed_transpiler": seed,
                "shots": 10000,
            }
            model._quantum_instance, model._backend = bc.configure_quantum_instance(
                ibmq_api_config=ibmq_config,
                run_type="hardware",
                backend_name="ibmq_toronto",
                **model._backend_config,
            )
            model._quantum_kernel = QuantumKernel(
                model._feature_map,
                quantum_instance=model._quantum_instance,
            )
        scores = model.decision_function(test_features)
        np.save(output_path + f"scores_n{args['ntest']}_k{args['kfolds']}.npy", scores)
        np.save(output_path + f"kernel_matrix_test.npy", model._kernel_matrix_test)
        scores_time_fina = perf_counter()
    else:
        print(f"Multiple k={args['kfolds']} folds...")

        with ProcessPoolExecutor() as executor:
            sig_workers = [executor.submit(get_scores, model, fold) for fold in sig_fold]
            bkg_workers = [executor.submit(get_scores, model, fold) for fold in bkg_fold]
            score_sig = np.array([worker.result() for worker in sig_workers])
            score_bkg = np.array([worker.result() for worker in bkg_workers])
        scores_all = np.concatenate((score_sig.flatten(), score_bkg.flatten()))

        print(
            f"Saving the signal and background k-fold scores in the folder: "
            + tcols.OKCYAN
            + f"{output_path}"
            + tcols.ENDC
        )
        np.save(
            output_path + f"sig_scores_n{args['ntest']}_k{args['kfolds']}.npy",
            score_sig,
        )
        np.save(
            output_path + f"bkg_scores_n{args['ntest']}_k{args['kfolds']}.npy",
            score_bkg,
        )

        if isinstance(model, OneClassQSVM):
            np.save(output_path + f"kernel_matrix_test.npy", model._kernel_matrix_test)
        ordered_labels = test_loader[1]
        util.plot_score_distributions(scores_all, ordered_labels, output_path, args['ntest'],'test')
        scores_time_fina = perf_counter()
    exec_time = scores_time_fina - scores_time_init
    print(
        tcols.OKGREEN
        + "Completed in: "
        + tcols.ENDC
        + f"{exec_time:2.2e} sec. or {exec_time/60:2.2e} min. "
        + tcols.ROCKET
    )


def get_arguments() -> dict:
    """Parses command line arguments and gives back a dictionary.

    Returns
    -------
    dict
        Dictionary with parsed arguments
    """

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--sig_path",
        type=str,
        required=True,
        help="Path to the signal/anomaly dataset (.h5 format).",
    )
    parser.add_argument(
        "--bkg_path",
        type=str,
        required=True,
        help="Path to the QCD background dataset (.h5 format).",
    )
    parser.add_argument(
        "--test_bkg_path",
        type=str,
        required=True,
        help="Path to the background testing dataset (.h5 format).",
    )
    parser.add_argument(
        "--model", type=str, required=True, help="The folder path of the QSVM model."
    )
    parser.add_argument(
        "--ntest", type=int, default=720, help="Number of test events for the QSVM."
    )
    parser.add_argument(
        "--kfolds", type=int, default=5, help="Number of k-validation/test folds used."
    )
    parser.add_argument(
        "--mod_quantum_instance",
        action="store_true",
        help="Reconfigure the quantum " "instance and backend.",
    )
    parser.add_argument(
        "--unsup",
        action="store_true",
        help="Flag to choose between unsupervised and supervised models",
    )
    parser.add_argument(
        '--config_file',
        type=str,
        help="Private configuation file for IBMQ API token"
    )
    args = parser.parse_args()

    args = {
        "sig_path": args.sig_path,
        "bkg_path": args.bkg_path,
        "test_bkg_path": args.test_bkg_path,
        "model": args.model,
        "ntest": args.ntest,
        "kfolds": args.kfolds,
        "mod_quantum_instance": args.mod_quantum_instance,
        "config_file": args.config_file,
        "unsup": args.unsup,
    }
    return args


if __name__ == "__main__":
    args = get_arguments()
    main(args)
