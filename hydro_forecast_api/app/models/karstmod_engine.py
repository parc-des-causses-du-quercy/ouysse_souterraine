"""
KarstMod engine — numba-compiled karst aquifer model functions.

These are pure numerical functions with no I/O. Copied from the original
modèle_Ouysse.py without modification to preserve validated behavior.
"""


# Numerical core transposed from the KarstMod model developed by SNO Karst researchers.
# Wrapping and packaging © 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# See LICENSE for ownership details on the scientific code (research/) vs the integration code.

import numpy as np
from numba import njit


@njit()
def to_q_m3_s(q_mm_h=np.array([], dtype=np.float64), area_km2=np.float64(0)):
    """Convert mm/h to m³/s."""
    return q_mm_h / 24 * area_km2


@njit()
def to_q_mm_h(q_m3_s=np.array([], dtype=np.float64), area_km2=np.float64(0)):
    """Convert m³/s to mm/h."""
    return q_m3_s * 3.6 * 24 / area_km2


@njit()
def ki_seuil(k=np.float64(0), a=np.float64(0), H=np.float64(0), Hseuil=np.float64(0)):
    """Threshold-dependent outflow coefficient."""
    return np.maximum(k * (H - Hseuil) ** (a - 1), 0)


@njit()
def Eth(E=np.float64(0), k=np.float64(0), S=np.float64(0), PAS=np.float64(0), Emin=np.float64(0)):
    """Exponential tank: water storage evolution with exponential approach to equilibrium."""
    if k != 0:
        Eq = S / k
        return np.maximum(Eq + (E - Eq) * np.exp(-k * PAS), Emin)
    else:
        return np.maximum(E + PAS * S, Emin)


@njit()
def MCth(M=np.float64(0), C=np.float64(0), kMC=np.float64(0), kM=np.float64(0),
         kC=np.float64(0), SM=np.float64(0), SC=np.float64(0), PAS=np.float64(0)):
    """Coupled matrix-conduit tank evolution with eigenvalue decomposition."""
    if (kM == 0) & (kC == 0):
        if kMC == 0:
            Mth = M
            Cth = C
        else:
            Mth = (M + C) / 2 + (SM + SC) * PAS / 2 + (SM - SC) / (4 * kMC) + (1 / 2) * (M - C - (SM - SC) / (2 * kMC)) * np.exp(-2 * kMC * PAS)
            Cth = (M + C) / 2 + (SM + SC) * PAS / 2 - (SM - SC) / (4 * kMC) - (1 / 2) * (M - C - (SM - SC) / (2 * kMC)) * np.exp(-2 * kMC * PAS)
    else:
        kM, kC, kMC = -kM, -kC, -kMC
        f1 = np.sqrt((kMC + (kC + kM) / 2) ** 2 - (kM * kMC + kC * kMC + kC * kM))
        l1 = -(kMC + (kC + kM) / 2) - f1
        l2 = -(kMC + (kC + kM) / 2) + f1
        det = kMC * kMC - (l1 + kMC + kM) * (l2 + kMC + kC)
        det_inv = 1 / det
        K100 = det_inv * kMC
        K101 = det_inv * (-l2 - kMC - kC)
        K110 = det_inv * (-l1 - kMC - kM)
        K111 = K100
        w00 = K100 * M + K101 * C
        w01 = K110 * M + K111 * C
        weq0 = (K100 * SM + K101 * SC) / l1
        weq1 = (K110 * SM + K111 * SC) / l2
        wp0 = weq0 + (w00 - weq0) * np.exp(-l1 * PAS)
        wp1 = weq1 + (w01 - weq1) * np.exp(-l2 * PAS)
        Mth = max(kMC * wp0 + (l2 + kMC + kC) * wp1, 0)
        Cth = max((l1 + kMC + kM) * wp0 + (kMC) * wp1, 0)
    return Mth, Cth


@njit()
def tf_E(pr=np.array([], dtype=np.float64), pet=np.array([], dtype=np.float64),
         Emin=np.float64(0),
         kEM=np.float64(0), aEM=np.float64(0),
         kEC=np.float64(0), aEC=np.float64(0),
         kES=np.float64(0), aES=np.float64(0),
         kloss=np.float64(0), aloss=np.float64(0), Eloss=np.float64(0),
         wl_initial=np.float64(0)):
    """Epikarst layer transfer function with RK2 integration."""

    QEM = np.zeros(len(pr) + 1, np.float64)
    QEC = np.zeros(len(pr) + 1, np.float64)
    QES = np.zeros(len(pr) + 1, np.float64)
    Qloss = np.zeros(len(pr) + 1, np.float64)
    wl = np.zeros(len(pr) + 1, np.float64)

    wl[0] = wl_initial

    for i in range(len(pr)):
        kEMi = ki_seuil(kEM, aEM, wl[i], Emin)
        kECi = ki_seuil(kEC, aEC, wl[i], Emin)
        kESi = ki_seuil(kES, aES, wl[i], Emin)
        klossi = ki_seuil(kloss, aloss, wl[i], Eloss)
        kE = kEMi + kECi + kESi + klossi

        SE = pr[i] - pet[i] - klossi * Eloss
        E12 = Eth(wl[i], kE, SE, 1 / 2, Emin)

        kEMi = ki_seuil(kEM, aEM, E12, Emin)
        kECi = ki_seuil(kEC, aEC, E12, Emin)
        kESi = ki_seuil(kES, aES, E12, Emin)
        klossi = ki_seuil(kloss, aloss, E12, Eloss)
        kE = kEMi + kECi + kESi + klossi

        SE = pr[i] - pet[i] - klossi * Eloss
        wl[i + 1] = Eth(wl[i], kE, SE, 1, Emin)

        if kE != 0:
            Qtot = max(SE + (wl[i] - wl[i + 1]) / 1, 0)
            Qloss[i] = max(klossi * (Qtot / kE - Eloss), 0)
            QES[i] = max(kESi * Qtot / kE, 0)
            QEC[i] = max(kECi * Qtot / kE, 0)
            QEM[i] = max(kEMi * Qtot / kE, 0)

    return QEM[:-1], QEC[:-1], QES[:-1], Qloss[:-1], wl[:-1], wl[-1]


@njit()
def tf_MC(input_M=np.array([], dtype=np.float64), output_M=np.array([], dtype=np.float64),
          input_C=np.array([], dtype=np.float64), output_C=np.array([], dtype=np.float64),
          kMC=np.float64(0), aMC=np.float64(0),
          C_loss=np.float64(0), M_loss=np.float64(0),
          kMS=np.float64(0), aMS=np.float64(0),
          kCS=np.float64(0), aCS=np.float64(0),
          C_initial=np.float64(0), M_initial=np.float64(0)):
    """Matrix-Conduit lower layer transfer function."""

    C = np.zeros(len(input_M) + 1, np.float64)
    M = np.zeros(len(input_M) + 1, np.float64)
    Q_C_loss = np.zeros(len(input_M) + 1, np.float64)
    Q_M_loss = np.zeros(len(input_M) + 1, np.float64)
    Q_M_S = np.zeros(len(input_M) + 1, np.float64)
    Q_C_S = np.zeros(len(input_M) + 1, np.float64)
    Q_M_C = np.zeros(len(input_M) + 1, np.float64)

    C[0] = C_initial
    M[0] = M_initial

    SM = input_M - output_M
    SC = input_C - output_C

    for i in range(len(input_M)):

        if kMC == 0 or M[i] == C[i] or M[i] <= 0 or C[i] <= 0:
            # Non-coupled M-C
            if C[i] > C_loss:
                Q_C_loss[i] = (C[i] - C_loss)
                C[i] = C_loss
            if M[i] > M_loss:
                Q_M_loss[i] = (M[i] - M_loss)
                M[i] = M_loss

            kMSi = ki_seuil(kMS, aMS, M[i], 0)
            M12 = np.minimum(Eth(M[i], kMSi, SM[i], 1 / 2, -1e5), M_loss)
            kMSi = ki_seuil(kMS, aMS, M12, 0)
            M[i + 1] = np.minimum(Eth(M[i], kMSi, SM[i], 1, -1e5), M_loss)
            Q_M_S[i] = np.maximum(SM[i] + (M[i] - M[i + 1]) / 1, 0)

            kCSi = ki_seuil(kCS, aCS, C[i], 0)
            C12 = np.minimum(Eth(C[i], kCSi, SC[i], 1 / 2, -1e5), C_loss)
            kCSi = ki_seuil(kCS, aCS, C12, 0)
            C[i + 1] = np.minimum(Eth(C[i], kCSi, SC[i], 1, -1e5), C_loss)
            Q_C_S[i] = np.maximum(SC[i] + (C[i] - C[i + 1]) / 1, 0)

        else:
            # Coupled M-C with RK2
            if M[i] > M_loss:
                Q_M_loss[i] = (M[i] - M_loss)
                M[i] = M_loss
            if C[i] > C_loss:
                Q_C_loss[i] = (C[i] - C_loss)
                C[i] = C_loss

            kMSi = ki_seuil(kMS, aMS, M[i], 0)
            kCSi = ki_seuil(kCS, aCS, C[i], 0)
            kMCi = ki_seuil(kMC, aMC, np.abs(M[i] - C[i]), 0)

            M12, C12 = MCth(M[i], C[i], kMCi, kMSi, kCSi, SM[i], SC[i], 1 / 2)
            M12 = np.minimum(M12, M_loss)
            C12 = np.minimum(C12, C_loss)

            kMSi = ki_seuil(kMS, aMS, M12, 0)
            kCSi = ki_seuil(kCS, aCS, C12, 0)
            kMCi = ki_seuil(kMC, aMC, np.abs(M12 - C12), 0)

            tmpM, tmpC = MCth(M[i], C[i], kMCi, kMSi, kCSi, SM[i], SC[i], 1)

            M[i + 1] = tmpM
            C[i + 1] = tmpC

            QMSCS = -(M[i + 1] - M[i]) - (C[i + 1] - C[i]) + SM[i] + SC[i]

            if QMSCS == 0 or (kMSi == 0 and kCSi == 0):
                Q_M_S[i] = 0
                Q_C_S[i] = 0
            else:
                Q_M_S[i] = QMSCS * (kMSi * (M[i] + M[i + 1])) / (kMSi * (M[i] + M[i + 1]) + kCSi * (C[i] + C[i + 1]))
                Q_C_S[i] = QMSCS - Q_M_S[i]

            Q_M_C[i] = (M[i] - M[i + 1]) + SM[i] - Q_M_S[i]

    qsim = np.maximum(Q_C_S + Q_M_S + Q_C_loss + Q_M_loss, 0)

    return qsim[:-1], C[:-1], M[:-1], C[-1], M[-1]


@njit()
def karstmod_engine(pr=np.array([], dtype=np.float64),
                    pet=np.array([], dtype=np.float64),
                    qsink_mm=np.array([], dtype=np.float64),
                    area=np.float64(0),
                    Emin=np.float64(0),
                    kEM=np.float64(0), aEM=np.float64(0),
                    kEC=np.float64(0), aEC=np.float64(0),
                    kES=np.float64(0), aES=np.float64(0),
                    kloss=np.float64(0), aloss=np.float64(0), Eloss=np.float64(0),
                    kCS=np.float64(0), aCS=np.float64(0),
                    kMS=np.float64(0), aMS=np.float64(0),
                    kMC=np.float64(0), aMC=np.float64(0),
                    wlE_initial=np.float64(0),
                    C_initial=np.float64(0),
                    M_initial=np.float64(0)):
    """Full KarstMod engine: epikarst -> matrix-conduit -> outlet discharge."""

    qEM, qEC, qES, qloss, wlE, wlE_final = tf_E(
        pr, pet, Emin, kEM, aEM, kEC, aEC, kES, aES, kloss, aloss, Eloss, wlE_initial
    )

    input_M = qEM
    output_M = np.zeros(len(pr), dtype=np.float64)
    input_C = qEC + qsink_mm
    output_C = np.zeros(len(pr), dtype=np.float64)

    qCS, wl_C, wl_M, C_final, M_final = tf_MC(
        input_M=input_M, output_M=output_M,
        input_C=input_C, output_C=output_C,
        kMC=kMC, aMC=aMC, C_loss=1e5, M_loss=1e5,
        kMS=kMS, aMS=aMS, kCS=kCS, aCS=aCS,
        C_initial=C_initial, M_initial=M_initial
    )

    qsim = to_q_m3_s(qCS, area)

    return qsim, wlE_final, C_final, M_final
