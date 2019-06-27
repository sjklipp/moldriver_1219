""" drivers
"""
import functools
import os
import warnings
import numpy
from qcelemental import constants as qcc
import automol
import elstruct
import autofile
from autofile import SFS
from autofile import RFS
from moldr import optsmat


DEG2RAD = qcc.conversion_factor('degree', 'radian')
ANG2BOHR = qcc.conversion_factor('angstrom', 'bohr')


def run_conformers(ich, charge, mult, method, basis, orb_restricted,
                   nsamp, run_prefix, save_prefix, script_str, prog,
                   **kwargs):
    """ run sampling algorithm to find conformers
    """
    geo = automol.inchi.geometry(ich)
    zma = automol.geom.zmatrix(geo)
    tors_names = automol.geom.zmatrix_torsion_coordinate_names(geo)
    tors_range_vals = automol.zmatrix.torsional_sampling_ranges(
        zma, tors_names)
    tors_ranges = dict(zip(tors_names, tors_range_vals))

    if not tors_ranges:
        print("No torsional coordinates. Setting nsamp to 1.")
        nsamp = 1

    root_specs = (ich, charge, mult, method, basis, orb_restricted)

    # check for a previously saved run
    vma = automol.zmatrix.var_(zma)
    if SFS.conf_trunk.dir.exists(save_prefix, root_specs):
        _vma = SFS.conf_trunk.file.vmatrix.read(save_prefix, root_specs)
        assert vma == _vma
        inf_obj = SFS.conf_trunk.file.info.read(save_prefix, root_specs)
        nsamp = max(nsamp - inf_obj.nsamp, 0)
        print("Found previous saved run. Adjusting nsamp.")
        print("    New nsamp is {:d}.".format(nsamp))
    else:
        SFS.conf_trunk.dir.create(save_prefix, root_specs)
        inf_obj = autofile.system.info.conformer_trunk(
            nsamp=0, tors_ranges=tors_ranges)
    SFS.conf_trunk.file.vmatrix.write(vma, save_prefix, root_specs)
    SFS.conf_trunk.file.info.write(inf_obj, save_prefix, root_specs)

    # update the number of samples

    inp_zmas = automol.zmatrix.samples(zma, nsamp, tors_ranges)

    cids = tuple(autofile.system.generate_new_conformer_id()
                 for _ in range(nsamp))

    print()
    print("Running optimizations in run directories.")
    for idx, (cid, inp_zma) in enumerate(zip(cids, inp_zmas)):
        specs = root_specs + (cid,)

        if not SFS.conf.dir.exists(run_prefix, specs):
            SFS.conf.dir.create(run_prefix, specs)

        path = SFS.conf.dir.path(run_prefix, specs)

        print("Run {}/{}".format(idx+1, nsamp))
        run_job(
            job=elstruct.Job.OPTIMIZATION,
            script_str=script_str,
            prefix=path,
            geom=inp_zma,
            charge=charge,
            mult=mult,
            method=method,
            basis=basis,
            prog=prog,
            **kwargs
        )


def save_conformers(ich, charge, mult, method, basis, orb_restricted,
                    run_prefix, save_prefix):
    """ save the conformers that have been found so far
    """
    root_specs = (ich, charge, mult, method, basis, orb_restricted)
    print('save_conf_test', run_prefix, root_specs)
    if SFS.conf_trunk.dir.exists(run_prefix, root_specs):
        run_conf_specs_lst = SFS.conf.dir.existing(run_prefix, root_specs)
        saved_conf_specs_lst = SFS.conf.dir.existing(save_prefix, root_specs)

        conf_specs_lst = []
        ene_lst = []
        geo_lst = []
        inp_str_lst = []
        inf_obj_lst = []

        print()
        print("Reading optimizations from run directories.")
        print(root_specs)
        run_specs = ('optimization',)
        for conf_specs in run_conf_specs_lst:
            specs = root_specs + conf_specs + run_specs

            run_path = SFS.conf_run.dir.path(run_prefix, specs)
            print("Reading from run at {}".format(run_path))

            if SFS.conf_run.file.output.exists(run_prefix, specs):
                inf_obj = SFS.conf_run.file.info.read(run_prefix, specs)
                inp_str = SFS.conf_run.file.input.read(run_prefix, specs)
                out_str = SFS.conf_run.file.output.read(run_prefix, specs)
                prog = inf_obj.prog
                if elstruct.reader.has_normal_exit_message(prog, out_str):
                    ene = elstruct.reader.energy(prog, method, out_str)
                    geo = elstruct.reader.opt_geometry(prog, out_str)

                    # save the information to a list
                    conf_specs_lst.append(conf_specs)
                    inf_obj_lst.append(inf_obj)
                    inp_str_lst.append(inp_str)
                    ene_lst.append(ene)
                    geo_lst.append(geo)

        seen_geo_lst = []
        for conf_specs in saved_conf_specs_lst:
            specs = root_specs + conf_specs
            geo = SFS.conf.file.geometry.read(save_prefix, specs)
            seen_geo_lst.append(geo)

        print("Writing unique conformer information to save directories.")
        idxs = automol.geom.argunique_coulomb_spectrum(
            geo_lst, seen_geos=seen_geo_lst, rtol=1e-3)
        for idx in idxs:
            conf_specs = conf_specs_lst[idx]
            inf_obj = inf_obj_lst[idx]
            inp_str = inp_str_lst[idx]
            ene = ene_lst[idx]
            geo = geo_lst[idx]

            specs = root_specs + conf_specs
            save_path = SFS.conf.dir.path(save_prefix, specs)
            print("Saving values from run at {}".format(save_path))

            SFS.conf.dir.create(save_prefix, specs)
            SFS.conf.file.geometry_info.write(inf_obj, save_prefix, specs)
            SFS.conf.file.geometry_input.write(inp_str, save_prefix, specs)
            SFS.conf.file.energy.write(ene, save_prefix, specs)
            SFS.conf.file.geometry.write(geo, save_prefix, specs)

        # update the number of samples
        nsamp_new = len(conf_specs_lst)
        trunk_inf_obj = SFS.conf_trunk.file.info.read(save_prefix, root_specs)
        trunk_inf_obj.nsamp += nsamp_new
        SFS.conf_trunk.file.info.write(trunk_inf_obj, save_prefix, root_specs)


def run_conformer_job(ich, charge, mult, method, basis, orb_restricted, job,
                      run_prefix, save_prefix, script_str, prog,
                      **kwargs):
    """ run a job at each conformer point
    """
    root_specs = (ich, charge, mult, method, basis, orb_restricted)

    for conf_specs in SFS.conf.dir.existing(save_prefix, root_specs):
        specs = root_specs + conf_specs
        geo = SFS.conf.file.geometry.read(save_prefix, specs)
        path = SFS.conf.dir.path(run_prefix, specs)

        print('Running conformer {}'.format(job))
        run_job(
            job=job,
            script_str=script_str,
            prefix=path,
            geom=geo,
            charge=charge,
            mult=mult,
            method=method,
            basis=basis,
            prog=prog,
            **kwargs
        )


def run_scan(ich, charge, mult, method, basis, orb_restricted, cid,
             run_prefix, save_prefix, script_str, prog, scan_incr=30.,
             # ncoords,
             **kwargs):
    """ run a scan
    """
    root_specs = (ich, charge, mult, method, basis, orb_restricted, cid)
    if not SFS.conf.file.geometry.exists(save_prefix, root_specs):
        print('Conformer geometry file does not exist. Skipping ...')
    else:
        geo = SFS.conf.file.geometry.read(save_prefix, root_specs)
        zma = automol.geom.zmatrix(geo)

        vma = automol.zmatrix.var_(zma)
        if SFS.scan_trunk.dir.exists(save_prefix, root_specs):
            _vma = SFS.scan_trunk.file.vmatrix.read(save_prefix, root_specs)
            assert vma == _vma
        SFS.scan_trunk.dir.create(save_prefix, root_specs)
        SFS.scan_trunk.file.vmatrix.write(vma, save_prefix, root_specs)

        print(root_specs)
        print("Running hindered rotor scan for {:s}".format(cid))

        tors_names = automol.geom.zmatrix_torsion_coordinate_names(geo)
        increment = scan_incr * DEG2RAD
        tors_linspace_vals = automol.zmatrix.torsional_scan_grids(
            zma, tors_names, increment)
        tors_linspaces = dict(zip(tors_names, tors_linspace_vals))

        for tors_name, linspace in tors_linspaces.items():
            branch_specs = root_specs + ([tors_name],)
            inf_obj = autofile.system.info.scan_branch({tors_name: linspace})

            SFS.scan_branch.dir.create(save_prefix, branch_specs)
            SFS.scan_branch.file.info.write(inf_obj, save_prefix, branch_specs)

            last_zma = zma

            grid = numpy.linspace(*linspace)
            npoint = len(grid)
            for grid_idx, grid_val in enumerate(grid):
                specs = branch_specs + ((grid_idx,),)
                inp_zma = automol.zmatrix.set_values(
                    last_zma, {tors_name: grid_val})

                if not SFS.scan.dir.exists(run_prefix, specs):
                    SFS.scan.dir.create(run_prefix, specs)

                path = SFS.scan.dir.path(run_prefix, specs)

                print("Point {}/{}".format(grid_idx+1, npoint))
                run_job(
                    job=elstruct.Job.OPTIMIZATION,
                    script_str=script_str,
                    prefix=path,
                    geom=inp_zma,
                    charge=charge,
                    mult=mult,
                    method=method,
                    basis=basis,
                    prog=prog,
                    frozen_coordinates=[tors_name],
                    **kwargs
                )


def save_scan(ich, charge, mult, method, basis, orb_restricted, cid,
              run_prefix, save_prefix):
    """ save geometries and energies from a scan
    """
    root_specs = (ich, charge, mult, method, basis, orb_restricted, cid)
    for branch_specs in SFS.scan_branch.dir.existing(run_prefix, root_specs):

        print("Reading constrained optimizations from run directories.")
        for scan_specs in SFS.scan.dir.existing(
                run_prefix, root_specs+branch_specs):

            specs = root_specs + branch_specs + scan_specs

            run_specs = specs + ('optimization',)
            run_path = SFS.scan_run.dir.path(run_prefix, run_specs)
            print("Reading from scan run at {}".format(run_path))

            if SFS.scan_run.file.output.exists(run_prefix, run_specs):
                inf_obj = SFS.scan_run.file.info.read(run_prefix, run_specs)
                inp_str = SFS.scan_run.file.input.read(run_prefix, run_specs)
                out_str = SFS.scan_run.file.output.read(run_prefix, run_specs)
                prog = inf_obj.prog
                if not elstruct.reader.has_normal_exit_message(prog, out_str):
                    print("Job failed. Skipping ...")
                else:
                    ene = elstruct.reader.energy(prog, method, out_str)
                    geo = elstruct.reader.opt_geometry(prog, out_str)

                    save_path = SFS.scan.dir.path(save_prefix, specs)
                    print("Saving values from scan run at {}"
                          .format(save_path))

                    SFS.scan.dir.create(save_prefix, specs)
                    SFS.scan.file.geometry_info.write(
                        inf_obj, save_prefix, specs)
                    SFS.scan.file.geometry_input.write(
                        inp_str, save_prefix, specs)
                    SFS.scan.file.energy.write(ene, save_prefix, specs)
                    SFS.scan.file.geometry.write(geo, save_prefix, specs)


def run_tau(ich, charge, mult, method, basis, orb_restricted,
            nsamp, run_prefix, save_prefix, script_str, prog,
            **kwargs):
    """ run sampling algorithm to find taus
    """
    geo = automol.inchi.geometry(ich)
    zma = automol.geom.zmatrix(geo)
    tors_names = automol.geom.zmatrix_torsion_coordinate_names(geo)
    tors_range_vals = automol.zmatrix.torsional_sampling_ranges(
        zma, tors_names)
    tors_ranges = dict(zip(tors_names, tors_range_vals))

    if not tors_ranges:
        print("No torsional coordinates. Setting nsamp to 1.")
        nsamp = 1

    root_specs = (ich, charge, mult, method, basis, orb_restricted)

    # check for a previously saved run
    vma = automol.zmatrix.var_(zma)
    if SFS.tau_trunk.dir.exists(save_prefix, root_specs):
        _vma = SFS.tau_trunk.file.vmatrix.read(save_prefix, root_specs)
        assert vma == _vma
        inf_obj = SFS.tau_trunk.file.info.read(save_prefix, root_specs)
        nsamp = max(nsamp - inf_obj.nsamp, 0)
        print("Found previous saved run. Adjusting nsamp.")
        print("    New nsamp is {:d}.".format(nsamp))
    else:
        SFS.tau_trunk.dir.create(save_prefix, root_specs)
        inf_obj = autofile.system.info.tau_trunk(
            nsamp=0, tors_ranges=tors_ranges)
    SFS.tau_trunk.file.vmatrix.write(vma, save_prefix, root_specs)
    SFS.tau_trunk.file.info.write(inf_obj, save_prefix, root_specs)

    # update the number of samples

    inp_zmas = automol.zmatrix.samples(zma, nsamp, tors_ranges)

    cids = tuple(autofile.system.generate_new_conformer_id()
                 for _ in range(nsamp))

    print()
    print("Running tau optimizations in run directories.")
    for idx, (cid, inp_zma) in enumerate(zip(cids, inp_zmas)):
        specs = root_specs + (cid,)

        if not SFS.tau.dir.exists(run_prefix, specs):
            SFS.tau.dir.create(run_prefix, specs)

        path = SFS.tau.dir.path(run_prefix, specs)

        print("Run {}/{}".format(idx+1, nsamp))
        run_job(
            job=elstruct.Job.OPTIMIZATION,
            script_str=script_str,
            prefix=path,
            geom=inp_zma,
            charge=charge,
            mult=mult,
            method=method,
            basis=basis,
            prog=prog,
            frozen_coordinates=tors_names,
            **kwargs
        )


def save_tau(ich, charge, mult, method, basis, orb_restricted,
             run_prefix, save_prefix):
    """ save the taus that have been found so far
    """
    root_specs = (ich, charge, mult, method, basis, orb_restricted)
    run_tau_specs_lst = SFS.tau.dir.existing(run_prefix, root_specs)

    tau_specs_lst = []

    print()
    print("Reading optimizations from run directories.")
    run_specs = ('optimization',)
    for tau_specs in run_tau_specs_lst:
        specs = root_specs + tau_specs + run_specs

        run_path = SFS.tau_run.dir.path(run_prefix, specs)
        print("Reading from run at {}".format(run_path))

        if SFS.tau_run.file.output.exists(run_prefix, specs):
            inf_obj = SFS.tau_run.file.info.read(run_prefix, specs)
            inp_str = SFS.tau_run.file.input.read(run_prefix, specs)
            out_str = SFS.tau_run.file.output.read(run_prefix, specs)
            prog = inf_obj.prog
            if elstruct.reader.has_normal_exit_message(prog, out_str):
                ene = elstruct.reader.energy(prog, method, out_str)
                geo = elstruct.reader.opt_geometry(prog, out_str)

            print(automol.geom.coulomb_spectrum(geo))
            save_specs = root_specs + tau_specs
            save_path = SFS.tau.dir.path(save_prefix, save_specs)
            print("Saving values from run at {}".format(save_path))

            SFS.tau.dir.create(save_prefix, save_specs)
            SFS.tau.file.geometry_info.write(inf_obj, save_prefix, save_specs)
            SFS.tau.file.geometry_input.write(inp_str, save_prefix, save_specs)
            SFS.tau.file.energy.write(ene, save_prefix, save_specs)
            SFS.tau.file.geometry.write(geo, save_prefix, save_specs)

    # update the number of samples
    nsamp_new = len(tau_specs_lst)
    trunk_inf_obj = SFS.tau_trunk.file.info.read(save_prefix, root_specs)
    trunk_inf_obj.nsamp += nsamp_new
    SFS.tau_trunk.file.info.write(trunk_inf_obj, save_prefix, root_specs)


def run_tau_job(ich, charge, mult, method, basis, orb_restricted, job,
                run_prefix, save_prefix, script_str, prog, vignore=1e10,
                **kwargs):
    """ save the taus that have been found so far
    """
    root_specs = (ich, charge, mult, method, basis, orb_restricted)

    print()
    print("Reading optimizations from run directories as prelude to hessians.")

    for tau_specs in SFS.tau.dir.existing(save_prefix, root_specs):
        specs = root_specs + tau_specs
        geo = SFS.tau.file.geometry.read(save_prefix, specs)
        ene = SFS.tau.file.energy.read(save_prefix, specs)
        if ene < vignore:
            path = SFS.tau.dir.path(run_prefix, specs)

            print("Running tau {}".format(job))
            run_job(
                job=job,
                script_str=script_str,
                prefix=path,
                geom=geo,
                charge=charge,
                mult=mult,
                method=method,
                basis=basis,
                prog=prog,
                **kwargs
            )


# gridopt functions
class ReactionType():
    """ reaction types """

    H_MIGRATION = 'HMIG'
    BETA_SCISSION = 'BSC'
    ADDITION = 'ADD'
    H_ABSTRACTION = 'HABS'


def run_gridopt(inchis_pair, charges_pair, mults_pair, method, basis, orb_restricted,
                run_prefix, save_prefix, script_str, prog,
                ts_mult, **kwargs):

    direction = autofile.system.reaction_direction(
        inchis_pair, charges_pair, mults_pair)
    print("The direction of the reaction is", direction)
    print("The transition state multiplicity is", ts_mult)
    reactant_inchis = inchis_pair[0]
    product_inchis = inchis_pair[1]

    reactant_geoms = list(map(automol.inchi.geometry, reactant_inchis))
    product_geoms = list(map(automol.inchi.geometry, product_inchis))

    reactant_zmats = list(map(automol.geom.zmatrix, reactant_geoms))
    product_zmats = list(map(automol.geom.zmatrix, product_geoms))

    ret = build_ts_zmatrix(reactant_zmats, product_zmats)
    if ret:
        ts_zmat, dist_name, reaction_type = ret

        if reaction_type == ReactionType.BETA_SCISSION:
            dist_start = automol.zmatrix.values(ts_zmat)[dist_name]
            npoints = 10
            dist_increment = 0.1 * ANG2BOHR  # hardcoded for now (0.2 bohr)
        elif reaction_type == ReactionType.ADDITION:
            dist_start = 1.2 * ANG2BOHR
            npoints = 10
            dist_increment = 0.1 * ANG2BOHR  # hardcoded for now (0.2 bohr)

        grid_zmats = [
            automol.zmatrix.set_values(
                ts_zmat, {dist_name: dist_start + dist_increment * num})
            for num in range(npoints)]

        for grid_zmat in grid_zmats:
            print(automol.zmatrix.string(grid_zmat))

    #         value_dict = automol.zmatrix.values(reac1_zmat)
    #         dist_name = name_matrix[atom2_key][0]
    #         dist_value = value_dict[dist_name]

    #         dist_increment = 0.2 # hardcoded for now (0.2 bohr)
    #         npoints = 10         # hardcoded for now
    #         grid_zmats = [
    #             automol.zmatrix.set_values(
    #                 reac1_zmat, {dist_name: dist_value + dist_increment * num})
    #             for num in range(npoints)
    #         ]

    #         # set up the run filesystem
    #         cid = autofile.system.generate_new_conformer_id()
    #         branch_specs = (inchis_pair, charges_pair, mults_pair, method, basis, orb_restricted,
    #                         cid, [dist_name])
    #         path = RFS.scan_branch.dir.path(run_prefix, branch_specs)
    #         RFS.scan_branch.dir.create(run_prefix, branch_specs)

    #         for grid_index, grid_zmat in enumerate(grid_zmats):
    #             specs = branch_specs + ((grid_index,),)

    #             if not RFS.scan.dir.exists(run_prefix, specs):
    #                 RFS.scan.dir.create(run_prefix, specs)

    #             path = RFS.scan.dir.path(run_prefix, specs)

    #             print("Point {}/{}".format(grid_index+1, npoints))
    #             run_job(
    #                 job=elstruct.Job.OPTIMIZATION,
    #                 script_str=script_str,
    #                 prefix=path,
    #                 geom=grid_zmat,
    #                 charge=charge,
    #                 mult=mult,
    #                 method=method,
    #                 basis=basis,
    #                 prog=prog,
    #                 frozen_coordinates=[dist_name],
    #                 **kwargs
    #             )

    # old, delete:
    # # get stereo-specific inchis from the geometries
    # reactant_inchis = list(map(automol.inchi.standard_form,
    #                        map(automol.geom.inchi, reactant_geoms)))
    # product_inchis = list(map(automol.inchi.standard_form,
    #                       map(automol.geom.inchi, product_geoms)))
    # inchis_pair = (reactant_inchis, product_inchis)
    # inchis_pair, charges_pair, mults_pair = autofile.system.sort_together(
    #     inchis_pair, charges_pair, mults_pair)

    # # space the geometries out to make sure they aren't overlapping
    # reactant_geoms = [
    #     automol.geom.translated(geom, [100. * num, 0., 0.])
    #     for num, geom in enumerate(reactant_geoms)]
    # product_geoms = [
    #     automol.geom.translated(geom, [100. * num, 0., 0.])
    #     for num, geom in enumerate(product_geoms)]

    # reactants_geom = functools.reduce(automol.geom.join, reactant_geoms)
    # products_geom = functools.reduce(automol.geom.join, product_geoms)

    # reactants_graph = automol.geom.graph(reactants_geom)
    # products_graph = automol.geom.graph(products_geom)

    # ret = classify(reactants_graph, products_graph)
    # if ret is not None:
    #     reaction_type, (bonds_formed, bonds_broken) = ret
    #     if reaction_type == ReactionType.ADDITION:
    #         mult = mults_pair[0][0]   # TODO: don't do this -- specifiers
    #                                   # should only be used for addresses in
    #                                   # the filesystem
    #         charge = 0
    #         bond_formed, = bonds_formed
    #         atom1_system_key, atom2_system_key = sorted(bond_formed)

    #         reac1_geom, reac2_geom = reactant_geoms
    #         reac1_zmat = automol.geom.zmatrix(reac1_geom)
    #         reac1_zmat_atom_ordering_dict = automol.geom.zmatrix_atom_ordering(reac1_geom)

    #         reac1_natoms = automol.zmatrix.count(reac1_zmat)
    #         reac2_zmat = automol.geom.zmatrix(reac2_geom)
    #         reac2_zmat = automol.zmatrix.standard_form(reac2_zmat, shift=reac1_natoms)
    #         reac2_zmat_atom_ordering_dict = automol.geom.zmatrix_atom_ordering(reac2_geom)

    #         atom1_key = reac1_zmat_atom_ordering_dict[atom1_system_key]
    #         atom2_key = reac2_zmat_atom_ordering_dict[atom2_system_key - reac1_natoms]

    #         reac1_graph = automol.zmatrix.graph(reac1_zmat)
    #         atom1_longest_chain = automol.graph.atom_longest_chains(reac1_graph)[atom1_key]
    #         atom1_neighbor_keys = automol.graph.atom_neighbor_keys(reac1_graph)[atom1_key]

    #         assert len(atom1_longest_chain) > 1
    #         atomj_key = atom1_longest_chain[1]
    #         if len(atom1_longest_chain) > 2:
    #             atomk_key = atom1_longest_chain[2]
    #         else:
    #             assert len(atom1_neighbor_keys) > 1
    #             atom1_neighbor_keys = sorted(atom1_neighbor_keys)
    #             atom1_neighbor_keys.remove(atomj_key)
    #             atomk_key = atom1_neighbor_keys[0]

    #         ts_zmat, dist_name = build_init_addn_ts_zmatrix(
    #             reac1_zmat, reac2_zmat, atom1_key, atomj_key, atomk_key)
    #         print(automol.zmatrix.string(ts_zmat))
    #         print(dist_name)

    #     elif reaction_type == ReactionType.BETA_SCISSION:
    #         mult = mults_pair[0][0]   # TODO: don't do this
    #         charge = 0
    #         reac1_zmat = automol.geom.zmatrix(reactants_geom)
    #         zmat_atom_ordering_dict = automol.geom.zmatrix_atom_ordering(reactants_geom)

    #         bond_broken, = bonds_broken
    #         atom1_key, atom2_key = sorted(map(zmat_atom_ordering_dict.__getitem__, bond_broken))

    #         key_matrix = automol.zmatrix.key_matrix(reac1_zmat)
    #         name_matrix = automol.zmatrix.name_matrix(reac1_zmat)
    #         assert key_matrix[atom2_key][0] == atom1_key



def build_ts_zmatrix(reactant_zmats, product_zmats):
    """ build the transition state z-matrix for a reaction
    """
    reactant_geoms = list(map(automol.zmatrix.geometry, reactant_zmats))
    product_geoms = list(map(automol.zmatrix.geometry, product_zmats))
    reactants_graph = combined_graph_from_zmatrices(reactant_zmats)
    products_graph = combined_graph_from_zmatrices(product_zmats)

    ret = classify(reactants_graph, products_graph)
    if ret is not None:
        reaction_type, (bonds_formed, bonds_broken) = ret
        if reaction_type == ReactionType.ADDITION:
            bond_formed, = bonds_formed
            atom1_system_key, atom2_system_key = sorted(bond_formed)

            reac1_geom, reac2_geom = reactant_geoms
            reac1_zmat, reac2_zmat = reactant_zmats

            reac1_natoms = automol.zmatrix.count(reac1_zmat)
            reac2_zmat = automol.zmatrix.standard_form(reac2_zmat, shift=reac1_natoms)

            reac1_isite_key = atom1_system_key
            reac2_atom_key = atom2_system_key

            reac1_graph = automol.zmatrix.graph(reac1_zmat)
            reac1_isite_longest_chain = automol.graph.atom_longest_chains(reac1_graph)[reac1_isite_key]
            reac1_isite_neighbor_keys = automol.graph.atom_neighbor_keys(reac1_graph)[reac1_isite_key]

            assert len(reac1_isite_longest_chain) > 1
            reac1_jsite_key = reac1_isite_longest_chain[1]
            if len(reac1_isite_longest_chain) > 2:
                reac2_ksite_key = reac1_isite_longest_chain[2]
            else:
                assert len(reac1_isite_neighbor_keys) > 1
                reac1_isite_neighbor_keys = sorted(reac1_isite_neighbor_keys)
                reac1_isite_neighbor_keys.remove(reac1_jsite_key)
                reac2_ksite_key = reac1_isite_neighbor_keys[0]

            ts_zmat, dist_name = build_init_addn_ts_zmatrix(
                reac1_zmat, reac2_zmat, reac1_isite_key, reac1_jsite_key, reac2_ksite_key)

        elif reaction_type == ReactionType.BETA_SCISSION:
            ts_zmat, = reactant_zmats

            bond_broken, = bonds_broken
            atom1_key, atom2_key = sorted(bond_broken)

            key_matrix = automol.zmatrix.key_matrix(ts_zmat)
            name_matrix = automol.zmatrix.name_matrix(ts_zmat)
            assert key_matrix[atom2_key][0] == atom1_key

            value_dict = automol.zmatrix.values(ts_zmat)
            dist_name = name_matrix[atom2_key][0]

    return ts_zmat, dist_name, reaction_type


def classify(xgr1, xgr2):
    """ classify a reaction by type
    """
    ret = None

    rxn = automol.graph.reaction.hydrogen_migration(xgr1, xgr2)
    if rxn and ret is None:
        typ = ReactionType.H_MIGRATION
        ret = (typ, rxn)

    rxn = automol.graph.reaction.beta_scission(xgr1, xgr2)
    if rxn and ret is None:
        typ = ReactionType.BETA_SCISSION
        ret = (typ, rxn)

    rxn = automol.graph.reaction.addition(xgr1, xgr2)
    if rxn and ret is None:
        typ = ReactionType.ADDITION
        ret = (typ, rxn)

    rxn = automol.graph.reaction.hydrogen_abstraction(xgr1, xgr2)
    if rxn and ret is None:
        typ = ReactionType.H_ABSTRACTION
        ret = (typ, rxn)

    return ret


def combined_graph_from_zmatrices(zmats):
    graphs = list(map(automol.zmatrix.graph, zmats))
    shift = 0
    for idx, graph in enumerate(graphs):
        graphs[idx] = automol.graph.transform_keys(graph, lambda x: x+shift)
        shift += len(automol.graph.atoms(graph))
    graph = functools.reduce(automol.graph.union, graphs)
    return graph


def build_init_addn_ts_zmatrix(reac1_zmat, reac2_zmat,
                               isite, jsite, ksite,
                               aabs1=DEG2RAD * 85.,
                               aabs2=DEG2RAD * 85.,
                               babs1=DEG2RAD * 180.,
                               babs2=DEG2RAD * 90.,
                               babs3=DEG2RAD * 90.,
                               standardize=False):
    """ Builds the initial ts z-matrix
        CHECK MANUAL, IS KSITE USED FOR ANYTHING?
    """
    reac1_natom = automol.zmatrix.count(reac1_zmat)
    reac2_natom = automol.zmatrix.count(reac2_zmat)

    # Set the RTS value to 111.11 as a holdover
    rts = 111.111

    # Set the join values for the Reac2 Z-Matrix values; based on Reac2 natom
    if reac2_natom == 1:
        r1_r2_join_keys = ((isite, jsite, ksite))
        r1_r2_join_name = (('rts', 'aabs1', 'babs1'))
        r1_r2_join_vals = {'rts': rts, 'aabs1': aabs1, 'babs1': babs1}
    elif reac2_natom == 2:
        r1_r2_join_keys = ((isite, jsite, ksite),
                            (None, isite, jsite))
        r1_r2_join_name = (('rts', 'aabs1', 'babs1'),
                            (None, 'aabs2', 'babs2'))
        r1_r2_join_vals = {'rts': rts, 'aabs1': aabs1, 'babs1': babs1,
                                        'aabs2': aabs2, 'babs2': babs2}
    else:
        r1_r2_join_keys = ((isite, jsite, ksite),
                            (None, isite, jsite),
                            (None, None, isite))
        r1_r2_join_name = (('rts', 'aabs1', 'babs1'),
                            (None, 'aabs2', 'babs2'),
                            (None, None, 'babs3'))
        r1_r2_join_vals = {'rts': rts, 'aabs1': aabs1, 'babs1': babs1,
                                        'aabs2': aabs2, 'babs2': babs2,
                                                        'babs3': babs3}

    # Join the Init TS and Reac2 Z-Matrices
    ts_zmat = automol.zmatrix.join(reac1_zmat, reac2_zmat,
                           r1_r2_join_keys, r1_r2_join_name, r1_r2_join_vals)
    
    # Put in standard form if requested
    if standardize:
        ts_zmat = zmatrix.standard_form(ts_zmat)

    # Get the scan_coord using the reac2_natom (lazy do better)
    scan_coord = ts_zmat[0][-1*reac2_natom][2][0]

    return ts_zmat, scan_coord

# end of gridopt functions

# centralized job runner
def run_job(job, script_str, prefix,
            geom, charge, mult, method, basis, prog,
            **kwargs):
    """ run an elstruct job by name
    """
    runner_dct = {
        elstruct.Job.ENERGY: functools.partial(elstruct.run.direct,
                                               elstruct.writer.energy),
        elstruct.Job.GRADIENT: functools.partial(elstruct.run.direct,
                                                 elstruct.writer.gradient),
        elstruct.Job.HESSIAN: functools.partial(elstruct.run.direct,
                                                elstruct.writer.hessian),
        elstruct.Job.OPTIMIZATION: feedback_optimization,
    }

    assert job in runner_dct

    run_trunk_ds = autofile.system.series.run_trunk()
    run_ds = autofile.system.series.run_leaf(root_dsdir=run_trunk_ds.dir)

    run_path = run_ds.dir.path(prefix, [job])
    if not run_ds.dir.exists(prefix, [job]):
        do_run = True
        print(" - Running {} job at {}".format(job, run_path))
    if run_ds.file.info.exists(prefix, [job]):
        inf_obj = run_ds.file.info.read(prefix, [job])
        if inf_obj.status == autofile.system.RunStatus.FAILURE:
            do_run = True
            print(" - Found failed {} job at {}".format(job, run_path))
            print(" - Removing and retrying...")
            run_ds.dir.remove(prefix, [job])
        else:
            do_run = False
            if inf_obj.status == autofile.system.RunStatus.SUCCESS:
                print(" - Found completed {} job at {}".format(job, run_path))
            else:
                print(" - Found running {} job at {}".format(job, run_path))
            print(" - Skipping...")

    if do_run:
        # create the run directory
        run_ds.dir.create(prefix, [job])

        run_path = run_ds.dir.path(prefix, [job])

        status = autofile.system.RunStatus.RUNNING
        inf_obj = autofile.system.info.run(
            job=job, prog=prog, method=method, basis=basis, status=status)
        inf_obj.utc_start_time = autofile.system.info.utc_time()
        run_ds.file.info.write(inf_obj, prefix, [job])

        runner = runner_dct[job]

        print(" - Starting the run...")
        inp_str, out_str = runner(
            script_str, run_path,
            geom=geom, charge=charge, mult=mult, method=method,
            basis=basis, prog=prog, **kwargs
        )

        inf_obj.utc_end_time = autofile.system.info.utc_time()

        if elstruct.reader.has_normal_exit_message(prog, out_str):
            run_ds.file.output.write(out_str, prefix, [job])
            print(" - Run succeeded.")
            status = autofile.system.RunStatus.SUCCESS
        else:
            print(" - Run failed.")
            status = autofile.system.RunStatus.FAILURE
        inf_obj.status = status
        run_ds.file.info.write(inf_obj, prefix, [job])
        run_ds.file.input.write(inp_str, prefix, [job])


def feedback_optimization(script_str, run_dir,
                          geom, charge, mult, method, basis, prog,
                          ntries=3, **kwargs):
    """ retry an optimization from the last (unoptimized) structure
    """
    assert automol.geom.is_valid(geom) or automol.zmatrix.is_valid(geom)
    is_zmat = automol.zmatrix.is_valid(geom)
    read_geom_ = (elstruct.reader.opt_geometry_(prog) if not is_zmat else
                  elstruct.reader.opt_zmatrix_(prog))
    has_noconv_error_ = functools.partial(
        elstruct.reader.has_error_message, prog, elstruct.Error.OPT_NOCONV)

    for try_idx in range(ntries):
        try_dir_name = 'try{:d}'.format(try_idx)
        try_dir_path = os.path.join(run_dir, try_dir_name)
        assert not os.path.exists(try_dir_path)
        os.mkdir(try_dir_path)

        # filter out the warnings from the trial runs
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            input_str, output_str = elstruct.run.direct(
                elstruct.writer.optimization, script_str, try_dir_path,
                geom=geom, charge=charge, mult=mult, method=method,
                basis=basis, prog=prog, **kwargs)

        if has_noconv_error_(output_str):
            geom = read_geom_(output_str)
        else:
            break

    if has_noconv_error_(output_str):
        warnings.resetwarnings()
        warnings.warn("elstruct feedback optimization failed; "
                      "last try was in {}".format(run_dir))

    return input_str, output_str


def robust_run(input_writer, script_str, run_dir,
               geom, charge, mult, method, basis, prog,
               errors=(), options_mat=(),
               **kwargs):
    """ try several sets of options to generate an output file
    :returns: the input string, the output string, and the run directory
    :rtype: (str, str, str)
    """
    assert len(errors) == len(options_mat)

    try_idx = 0
    kwargs_dct = dict(kwargs)
    while not optsmat.is_exhausted(options_mat):
        if try_idx > 0:
            kwargs_dct = optsmat.updated_kwargs(kwargs, options_mat)
        try_dir_name = 'try{:d}'.format(try_idx)
        try_dir_path = os.path.join(run_dir, try_dir_name)
        assert not os.path.exists(try_dir_path)
        os.mkdir(try_dir_path)

        # filter out the warnings from the trial runs
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            input_str, output_str = elstruct.run.direct(
                input_writer, script_str, try_dir_path,
                geom=geom, charge=charge, mult=mult, method=method,
                basis=basis, prog=prog, **kwargs_dct)

        error_vals = [
            elstruct.reader.has_error_message(prog, error, output_str)
            for error in errors]

        if not any(error_vals):
            break

        try_idx += 1
        row_idx = error_vals.index(True)
        options_mat = optsmat.advance(row_idx, options_mat)

    if (any(error_vals) or not
            elstruct.reader.has_normal_exit_message(prog, output_str)):
        warnings.resetwarnings()
        warnings.warn("elstruct robust run failed; last run was in {}"
                      .format(run_dir))

    return input_str, output_str


def robust_feedback_opt(script_str, run_dir,
                        geom, charge, mult, method, basis, prog,
                        errors=(), options_mat=(), ntries=3, **kwargs):
    """ try several sets of options to generate an output file
        retry an optimization from the last (unoptimized) structure
    """
    assert automol.geom.is_valid(geom) or automol.zmatrix.is_valid(geom)
    is_zmat = automol.zmatrix.is_valid(geom)
    read_geom_ = (elstruct.reader.opt_geometry_(prog) if not is_zmat else
                  elstruct.reader.opt_zmatrix_(prog))
    has_no_opt_conv_error_ = functools.partial(
        elstruct.reader.has_error_message, prog, elstruct.Error.OPT_NOCONV)

    for try_idx in range(ntries):
        try_dir_name = 'try{:d}'.format(try_idx)
        try_dir_path = os.path.join(run_dir, try_dir_name)
        assert not os.path.exists(try_dir_path)
        os.mkdir(try_dir_path)

        # filter out the warnings from the trial runs
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            input_str, output_str = robust_run(
                elstruct.writer.optimization, script_str, try_dir_path,
                geom=geom, charge=charge, mult=mult, method=method,
                basis=basis, prog=prog, errors=errors, options_mat=options_mat,
                **kwargs)

        if has_no_opt_conv_error_(output_str):
            geom = read_geom_(output_str)
        else:
            break

    if has_no_opt_conv_error_(output_str):
        warnings.resetwarnings()
        warnings.warn("elstruct feedback optimization failed; "
                      "last try was in {}".format(run_dir))

    return input_str, output_str
