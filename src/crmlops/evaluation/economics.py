"""Economia de la decision: de probabilidades a dolares.

Un AUC no le sirve a nadie que tenga que decidir. Lo que importa es cuanta
perdida se evita y a que costo.

DECISION DE DISENO -- no se descompone en LGD x EAD. La formula clasica
EL = PD x LGD x EAD exige el saldo expuesto al momento del default, que el
extracto FOIA no trae; habria que inventarlo. En cambio se modela directamente
E[monto de perdida | default], que SI es observable (GrossChargeOffAmount).
Menos elegante, mas honesto.

CONTRAFACTUAL Y SU LIMITE -- todos los prestamos del panel fueron aprobados, asi
que se observa que habria pasado al rechazar a los peores segun el modelo. El
supuesto que esto exige y que hay que declarar: que rechazar no cambia el
comportamiento del resto (ni del prestatario, ni del banco, ni del mercado).
Para un ejercicio de dimensionamiento es razonable; para politica de credito real
haria falta un experimento.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DecisionPoint:
    decline_rate: float
    n_declined: int
    loss_avoided: float  # dolares de charge-off evitados
    good_volume_foregone: float  # dolares prestados a buenos que se rechazaron
    bad_declined: int
    good_declined: int
    precision: float  # % de rechazados que efectivamente fallaron
    loss_capture: float  # % del total de perdidas capturado


def decision_curve(
    y: np.ndarray,
    pd_score: np.ndarray,
    loss_amount: np.ndarray,
    exposure: np.ndarray,
    *,
    grid: np.ndarray | None = None,
) -> pd.DataFrame:
    """Que pasa al rechazar el k% mas riesgoso segun el modelo.

    `loss_amount` es 0 para los que pagaron y el monto cargado a perdida para los
    que fallaron. `exposure` es el monto prestado (para medir el volumen bueno
    que se sacrifica).
    """
    y = np.asarray(y)
    order = np.argsort(-np.asarray(pd_score))  # de mas riesgoso a menos
    y_s, loss_s, exp_s = y[order], np.asarray(loss_amount)[order], np.asarray(exposure)[order]

    total_loss = loss_s.sum()
    n = len(y)
    grid = grid if grid is not None else np.arange(0.01, 0.51, 0.01)

    rows = []
    for k in grid:
        m = round(k * n)
        if m == 0:
            continue
        head_y, head_loss, head_exp = y_s[:m], loss_s[:m], exp_s[:m]
        bad = int(head_y.sum())
        rows.append(
            DecisionPoint(
                decline_rate=float(k),
                n_declined=m,
                loss_avoided=float(head_loss.sum()),
                good_volume_foregone=float(head_exp[head_y == 0].sum()),
                bad_declined=bad,
                good_declined=m - bad,
                precision=bad / m,
                loss_capture=float(head_loss.sum() / total_loss) if total_loss else 0.0,
            ).__dict__
        )
    return pd.DataFrame(rows)


def random_baseline(
    y: np.ndarray, loss_amount: np.ndarray, exposure: np.ndarray, grid: np.ndarray
) -> pd.DataFrame:
    """Rechazar al azar. Es el piso contra el que se mide el modelo.

    En expectativa, rechazar k% al azar evita k% de las perdidas.
    """
    total_loss = float(np.sum(loss_amount))
    total_exp_good = float(np.sum(np.asarray(exposure)[np.asarray(y) == 0]))
    return pd.DataFrame(
        {
            "decline_rate": grid,
            "loss_avoided": grid * total_loss,
            "good_volume_foregone": grid * total_exp_good,
        }
    )


def breakeven_margin(loss_amount: np.ndarray, exposure: np.ndarray) -> float:
    """Margen minimo para que la cartera no pierda plata sin ningun modelo.

    Si el margen supuesto esta por debajo de este numero, la cartera es
    deficitaria en promedio y "rechazar mas" siempre mejora el resultado. En ese
    regimen el corte optimo se va al borde de la grilla y deja de ser
    informativo: lo que manda es el supuesto, no el modelo.
    """
    total_exp = float(np.sum(exposure))
    return float(np.sum(loss_amount) / total_exp) if total_exp else float("nan")


def optimal_cutoff(curve: pd.DataFrame, margin: float) -> pd.Series:
    """Corte que maximiza el beneficio neto para un margen dado.

    `margin` es la ganancia neta como fraccion del monto prestado en un prestamo
    bueno. Es un SUPUESTO, no un dato: por eso el corte optimo se reporta como
    funcion del margen y no como un numero unico. Un margen del 3% y uno del 8%
    dan politicas de credito distintas, y esa sensibilidad es informacion.

    `at_boundary` marca cuando el optimo cae en el extremo de la grilla. Ese caso
    NO debe reportarse como recomendacion: significa que la funcion objetivo
    crece de forma monotona y el verdadero optimo esta fuera del rango buscado.
    """
    net = curve["loss_avoided"] - margin * curve["good_volume_foregone"]
    best = curve.loc[net.idxmax()].copy()
    best["margin"] = margin
    best["net_benefit"] = float(net.max())
    best["at_boundary"] = bool(net.idxmax() in (curve.index.min(), curve.index.max()))
    return best


def summarize_at(curve: pd.DataFrame, decline_rate: float) -> pd.Series:
    """Fila de la curva mas cercana a una tasa de rechazo dada."""
    return curve.iloc[(curve["decline_rate"] - decline_rate).abs().idxmin()]
