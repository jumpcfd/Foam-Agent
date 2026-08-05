Compute the two-dimensional flow past a circular cylinder at a Reynolds number of 100.

The cylinder has a diameter of 1 m and sits in a uniform stream of 1 m/s. The fluid is
incompressible and Newtonian with a kinematic viscosity of 0.01 m^2/s, which puts the
Reynolds number based on the diameter at 100. At this Reynolds number the wake sheds
vortices periodically, so the flow is unsteady and laminar. It is two-dimensional: use a
single cell in the spanwise direction with empty boundaries. Put the outer boundaries far
enough from the cylinder that they do not change the wake.

Run long enough for the shedding to settle into a periodic state, then keep running for
several more shedding cycles. Report, over a whole number of cycles taken after the
transient:

- the time-averaged drag coefficient, using the cylinder diameter as the reference length
  and the free-stream speed as the reference velocity
- the Strouhal number of the shedding, f D / U

Use the forceCoeffs function object so that the coefficient histories are written under
postProcessing/, and put your two numbers in results.json in the case directory as
{"Cd_mean": ..., "St": ...}. Say in spec.md which time interval you averaged over and how
you decided the transient was over.
