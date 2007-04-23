"""Regression testing framework
This module will search for scripts in the same directory named
test_*.py.  Each such script should be a test suite that tests a
module through PyUnit. This script will aggregate all
found test suites into one big test suite and run them all at once.
"""

# Author: Mark Pilgrim
# Modified by Ole Nielsen

import unittest
import os
import sys
import tempfile


#List files that should be excluded from the testing process.
#E.g. if they are known to fail and under development

exclude_files = []
if sys.platform != 'win32':  #Windows
    exclude_files.append('test_advection.py') #Weave doesn't work on Linux

exclude_dirs = ['pypar_dist', #Special requirements
                'props', 'wcprops', 'prop-base', 'text-base', '.svn', #Svn
                'tmp']


print "The following directories will be skipped over;"
for dir in exclude_dirs:
    print dir
print ""

def get_test_files(path):


    try:
        files = os.listdir(path)
    except:
        return []

    #Check sub directories
    test_files = []

    #Exclude svn admin dirs
    files = [x for x in files if x not in exclude_dirs]
    path_files = []
    for file in files:

        absolute_filename = path + os.sep + file

        #sys.path.append('pmesh')
        if os.path.isdir(absolute_filename):
            sys.path.append(file) #FIXME: May cause name conflicts between pyvolution\mesh.py and pmesh\mesh.py on some systems
            path_files.append(file)
            print 'Recursing into', file
            more_test_files, more_path_files =get_test_files(absolute_filename)
            test_files += more_test_files
            path_files += more_path_files
        elif file.startswith('test_') and file.endswith('.py'):
            test_files.append(file)
        else:
            pass
    return test_files , path_files



def regressionTest(test_verbose=False):
    path = os.getcwd()
    test_files, path_files = get_test_files(path)
    files = [x for x in test_files if not x == 'test_all.py']

    print 'Testing path %s:' %('...'+path[-50:])
    for file in files:
        print '  ' + file
    if globals().has_key('exclude_files'):
        for file in exclude_files:
            print 'WARNING: File '+ file + ' to be excluded from testing'
        try:    
            files.remove(file)
        except ValueError, e:
            msg = 'File "%s" was not found in test suite.\n' %file
            msg += 'Original error is "%s"\n' %e
            msg += 'Perhaps it should be removed from exclude list?' 
            raise Exception, msg

    filenameToModuleName = lambda f: os.path.splitext(f)[0]
    moduleNames = map(filenameToModuleName, files)
    modules = map(__import__, moduleNames)
    # Fix up the system path
    for file in path_files:
        sys.path.remove(file)
    load = unittest.defaultTestLoader.loadTestsFromModule
    testCaseClasses = map(load, modules)
    if test_verbose is True:
        print "moduleNames", moduleNames 
        print "modules", modules
        print "load", load
        #print "weak", testCaseClasses.countTestCases()
        #sys.exit()
        i=0
        from anuga.shallow_water.test_data_manager import Test_Data_Manager
        from anuga.geospatial_data.test_geospatial_data import Test_Geospatial_data
        #print "test_data_manager.Test_Data_Manager", type(Test_Data_Manager)
        for test_suite in testCaseClasses:
            i += 1
            print "counting ", i
            #testCaseClass.classVerbose = True
            #testCaseClass.Verbose = True
            #print "testCaseClass",testCaseClass
            #print "testCaseClass",type(tests)
            #print "weak", tests.countTestCases()
            #print "weak", tests.__weakref__
            #print "dic",  tests.__dict__
            #print "testCaseClass.tests",  testCaseClass._tests[0]._tests[0].yah()
            for tests in test_suite._tests:
                #tests is of class TestSuite
                print "tests weak", tests.__weakref__
                if len(tests._tests) >1:
                    # these are the test functions
                    print "tests._tests[0]", tests._tests[0]
                    print "tests._tests[0]", tests._tests[0].__dict__
                    #print "tests._tests[0]", tests._tests[0].__name__
                    try:
                        # Calls set_verbose in the test case classes
                        tests._tests[0].set_verbose()
                    except:
                        pass # No all classes have
                    tests._tests[0].verbose=True # A call methods
                    if type(tests._tests[0]) == type(Test_Data_Manager):
                        print "testCaseClass is the class Test_Data_Manager"
                        sys.exit()
                
                    if type(tests._tests[0]) == type(Test_Geospatial_data):
                        print "testCaseClass is the class Test_Data_Manager"
                        sys.exit()
            if isinstance(tests, Test_Data_Manager):
                print "testCaseClass is an instance of Test_Data_Manager"
                sys.exit()
            if type(tests) == type(Test_Data_Manager):
                print "testCaseClass is the class Test_Data_Manager"
                sys.exit()
            
        #sys.exit()   
    return unittest.TestSuite(testCaseClasses)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1][0].upper() == 'V':
        test_verbose = True
        saveout = sys.stdout   
        filename = ".temp"
        fid = open(filename, 'w')
        sys.stdout = fid
    else:
        test_verbose = False        
    suite = regressionTest(test_verbose)
    runner = unittest.TextTestRunner() #verbosity=2
    runner.run(suite)
    
    # Cleaning up
    if len(sys.argv) > 1 and sys.argv[1][0].upper() == 'V':
        sys.stdout = saveout 
        #fid.close() # This was causing an error in windows
        #os.remove(filename)

