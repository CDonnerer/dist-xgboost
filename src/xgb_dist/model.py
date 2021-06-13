"""XGBDistribution model
"""
import numpy as np
import xgboost as xgb
from xgboost.sklearn import _wrap_evaluation_matrices, xgboost_model_doc

from sklearn.base import RegressorMixin

from xgb_dist.distributions import get_distribution, get_distribution_doc


@xgboost_model_doc(
    "Implementation of XGBoost to estimate distributions (scikit-learn API).",
    ["model"],
    extra_parameters=get_distribution_doc(),
)
class XGBDistribution(xgb.XGBModel, RegressorMixin):
    def __init__(self, distribution=None, natural_gradient=True, **kwargs):
        self.distribution = distribution or "normal"
        self.natural_gradient = natural_gradient
        super().__init__(objective=None, **kwargs)

    def fit(self, X, y, *, eval_set=None, early_stopping_rounds=None, verbose=True):

        self._distribution = get_distribution(self.distribution)

        params = self.get_xgb_params()
        params["disable_default_eval_metric"] = True
        params["num_class"] = len(self._distribution.params)

        # we set base score to zero to instead use base_margin in dmatrices
        # this allows different starting values for the distribution params
        params["base_score"] = 0.0
        self._starting_params = self._distribution.starting_params(y)

        base_margin = self._get_base_margins(len(y))
        if eval_set is not None:
            base_margin_eval_set = [
                self._get_base_margins(len(evals[1])) for evals in eval_set
            ]
        else:
            base_margin_eval_set = None

        train_dmatrix, evals = _wrap_evaluation_matrices(
            missing=self.missing,
            X=X,
            y=y,
            group=None,
            qid=None,
            sample_weight=None,
            base_margin=base_margin,
            feature_weights=None,
            eval_set=eval_set,
            sample_weight_eval_set=None,
            base_margin_eval_set=base_margin_eval_set,
            eval_group=None,
            eval_qid=None,
            create_dmatrix=lambda **kwargs: xgb.DMatrix(nthread=self.n_jobs, **kwargs),
            label_transform=lambda x: x,
        )

        self._Booster = xgb.train(
            params,
            train_dmatrix,
            num_boost_round=self.get_num_boosting_rounds(),
            evals=evals,
            early_stopping_rounds=early_stopping_rounds,
            obj=self._objective_func(),
            feval=self._evaluation_func(),
            verbose_eval=verbose,
        )
        return self

    def predict_dist(
        self,
        X,
        ntree_limit=None,
        validate_features=False,
        iteration_range=None,
    ):
        """Predict all params of the distribution"""

        if not hasattr(self, "_distribution"):
            self._distribution = get_distribution(self.distribution)

        base_margin = self._get_base_margins(X.shape[0])

        params = super().predict(
            X=X,
            output_margin=True,
            ntree_limit=ntree_limit,
            validate_features=validate_features,
            base_margin=base_margin,
            iteration_range=iteration_range,
        )
        return self._distribution.predict(params)

    def predict(
        self,
        X,
        ntree_limit=None,
        validate_features=False,
        iteration_range=None,
    ):
        """Predict the first param of the distribution, typically the mean"""
        return self.predict_dist(
            X=X,
            ntree_limit=ntree_limit,
            validate_features=validate_features,
            iteration_range=iteration_range,
        )[0]

    def _objective_func(self):
        def obj(params: np.ndarray, data: xgb.DMatrix):
            y = data.get_label()
            grad, hess = self._distribution.gradient_and_hessian(
                y, params, self.natural_gradient
            )
            return grad.flatten(), hess.flatten()

        return obj

    def _evaluation_func(self):
        def feval(params: np.ndarray, data: xgb.DMatrix):
            y = data.get_label()
            return self._distribution.loss(y, params)

        return feval

    def _get_base_margins(self, n_samples):
        return (
            np.array(
                [param * np.ones(shape=(n_samples,)) for param in self._starting_params]
            )
            .transpose()
            .flatten()
        )
