"""Parsers for extracting alchemical data from `Gromacs <http://www.gromacs.org/>`_ output files.

"""
import pandas as pd

from .util import anyopen


# TODO: perhaps move constants elsewhere?
# these are the units we need for dealing with gromacs, so not
# a bad place for it, honestly
k_b = 8.3144621E-3


def extract_u_nk(xvg, T):
    """Return reduced potentials `u_nk` from a Hamiltonian differences XVG file.

    Parameters
    ----------
    xvg : str
        Path to XVG file to extract data from.
    T : float
        Temperature in Kelvin the simulations sampled.

    Returns
    -------
    u_nk : DataFrame
        Potential energy for each alchemical state (k) for each frame (n).

    """

    h_col_match = r"\xD\f{}H \xl\f{}"
    pv_col_match = 'pV'
    u_col_match = ['Total Energy', 'Potential Energy']
    beta = 1/(k_b * T)

    state, lambdas, statevec = _extract_state(xvg)

    # extract a DataFrame from XVG data
    df = _extract_dataframe(xvg)

    # drop duplicate columns if we (stupidly) have them
    df = df.iloc[:, ~df.columns.duplicated()]

    times = df[df.columns[0]]

    # want to grab only dH columns
    DHcols = [col for col in df.columns if (h_col_match in col)]
    dH = df[DHcols]

    # gromacs also gives us pV directly; need this for reduced potential
    pv_cols = [col for col in df.columns if (pv_col_match in col)]
    pv = None
    if pv_cols:
        pv = df[pv_cols[0]]

    # gromacs also gives us total/potential energy U directly; need this for reduced potential
    u_cols = [col for col in df.columns if any(single_u_col_match in col for single_u_col_match in u_col_match)]
    u = None
    if u_cols:
        u = df[u_cols[0]]

    u_k = dict()
    cols = list()
    for col in dH:
        u_col = eval(col.split('to')[1])
        # calculate reduced potential u_k = dH + pV + U
        u_k[u_col] = beta * dH[col].values
        if pv_cols:
            u_k[u_col] += beta * pv.values
        if u_cols:
            u_k[u_col] += beta * u.values
        cols.append(u_col)

    u_k = pd.DataFrame(u_k, columns=cols,
                       index=pd.Float64Index(times.values, name='time'))

    # create columns for each lambda, indicating state each row sampled from
    # if state is None run as expanded ensemble data or REX
    if state is None:
        # if thermodynamic state is specified map thermodynamic
        # state data to lambda values, else (for REX)
        # define state based on the legend
        if 'Thermodynamic state' in df:
            ts_index = df.columns.get_loc('Thermodynamic state')
            thermo_state = df[df.columns[ts_index]]
            for i, l in enumerate(lambdas):
                v = []
                for t in thermo_state:
                    v.append(statevec[int(t)][i])
                u_k[l] = v
        else:
            state_legend = _extract_legend(xvg)
            for i, l in enumerate(state_legend):
                u_k[l] = state_legend[l]
    else:
        for i, l in enumerate(lambdas):
            try:
                u_k[l] = statevec[i]
            except TypeError:
                u_k[l] = statevec

    # set up new multi-index
    newind = ['time'] + lambdas
    u_k = u_k.reset_index().set_index(newind)

    u_k.name = 'u_nk'

    return u_k


def extract_dHdl(xvg, T):
    """Return gradients `dH/dl` from a Hamiltonian differences XVG file.

    Parameters
    ----------
    xvg : str
        Path to XVG file to extract data from.

    Returns
    -------
    dH/dl : Series
        dH/dl as a function of time for this lambda window.

    """
    beta = 1/(k_b * T)

    state, lambdas, statevec = _extract_state(xvg)

    # extract a DataFrame from XVG data
    df = _extract_dataframe(xvg)

    times = df[df.columns[0]]

    # want to grab only dH/dl columns
    dHcols = []
    for l in lambdas:
        dHcols.extend([col for col in df.columns if (l in col)])

    dHdl = df[dHcols]

    # make dimensionless
    dHdl = beta * dHdl

    # rename columns to not include the word 'lambda', since we use this for
    # index below
    cols = [l.split('-')[0] for l in lambdas]

    dHdl = pd.DataFrame(dHdl.values, columns=cols,
                        index=pd.Float64Index(times.values, name='time'))

    # create columns for each lambda, indicating state each row sampled from
    # if state is None run as expanded ensemble data or REX
    if state is None:
        # if thermodynamic state is specified map thermodynamic
        # state data to lambda values, else (for REX)
        # define state based on the legend
        if 'Thermodynamic state' in df:
            ts_index = df.columns.get_loc('Thermodynamic state')
            thermo_state = df[df.columns[ts_index]]
            for i, l in enumerate(lambdas):
                v = []
                for t in thermo_state:
                    v.append(statevec[int(t)][i])
                dHdl[l] = v
        else:
            state_legend = _extract_legend(xvg)
            for i, l in enumerate(state_legend):
                dHdl[l] = state_legend[l]
    else:
        for i, l in enumerate(lambdas):
            try:
                dHdl[l] = statevec[i]
            except TypeError:
                dHdl[l] = statevec

    # set up new multi-index
    newind = ['time'] + lambdas
    dHdl= dHdl.reset_index().set_index(newind)

    dHdl.name='dH/dl'

    return dHdl


def _extract_state(xvg):
    """Extract information on state sampled, names of lambdas.

    """
    state = None
    with anyopen(xvg, 'r') as f:
        for line in f:
            if ('subtitle' in line) and ('state' in line):
                state = int(line.split('state')[1].split(':')[0])
                lambdas = [word.strip(')(,') for word in line.split() if 'lambda' in word]
                statevec = eval(line.strip().split(' = ')[-1].strip('"'))
                break

    # if expanded ensemble data is used the state variable will never be assigned
    # parsing expanded ensemble data
    if state is None:
        lambdas = []
        statevec = []
        with anyopen(xvg, 'r') as f:
            for line in f:
                if ('legend' in line) and ('lambda' in line):
                    lambdas.append([word.strip(')(,') for word in line.split() if 'lambda' in word][0])
                if ('legend' in line) and (' to ' in line):
                    statevec.append(([float(i) for i in line.strip().split(' to ')[-1].strip('"()').split(',')]))

    return state, lambdas, statevec


def _extract_legend(xvg):
    """Extract information on state sampled for REX simulations.

    """
    state_legend = {}
    with anyopen(xvg, 'r') as f:
        for line in f:
            if ('legend' in line) and ('lambda' in line):
                state_legend[line.split()[4]] = float(line.split()[6].strip('"'))

    return state_legend


def _extract_dataframe(xvg):
    """Extract a DataFrame from XVG data.

    """
    with anyopen(xvg, 'r') as f:
        names = []
        rows = []
        for line in f:
            line = line.strip()
            if len(line) == 0:
                continue

            if "label" in line and "xaxis" in line:
                xaxis = line.split('"')[-2]

            if line.startswith("@ s") and "subtitle" not in line:
                name = line.split("legend ")[-1].replace('"','').strip()
                names.append(name)

            # should catch non-numeric lines so we don't proceed in parsing
            # here
            if line.startswith(('#', '@')):
                continue

            if line.startswith('&'):  #pragma: no cover
                raise NotImplementedError('{}: Multi-data not supported,'
                                          'only simple NXY format.'.format(xvg))
            # parse line as floats
            row = map(float, line.split())
            rows.append(row)

    cols = [xaxis]
    cols.extend(names)

    return pd.DataFrame(rows, columns=cols)
