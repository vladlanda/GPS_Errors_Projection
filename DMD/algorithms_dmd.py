import numpy as np

def DMD(X,Xprime,r=None,thr=1e-10):
    
    U,S,Vt = np.linalg.svd(X,full_matrices=False)
    n_rows,n_cols = X.shape
    if r is None:
        r = np.sum(S > thr)
    # r = int(np.ceil(r))
    Ur = U[:,:r]
    Sr = np.diag(S[:r])
    Vtr = Vt[:r,:]

    Atilda = Ur.T @ Xprime @ Vtr.T @ np.diag(1.0/S[:r])
    W,Lambda = np.linalg.eig(Atilda)
    W = np.diag(W)
    Phi = Xprime @ Vtr.T @ np.diag(1.0/S[:r]) @ W
    
    return (Phi,Ur,Atilda,np.nan)


def DMD_prediction(maps,n_pred_days=1,n_daily_samples = 12):

    n_samples = n_pred_days * n_daily_samples

    d,s,h,w = maps.shape
    A = maps.reshape(d*s,h*w).T

    X = A[:,:-1]
    Xprime = A[:,1:]

    (Phi,Ur_prime,A_tilda,_) = DMD(X,Xprime)

    pred_maps = []
    a = A[:,-1]

    for sample_idx in range(n_samples):
        a_tilda = Ur_prime.T @ a
        p = Ur_prime @ (A_tilda @ a_tilda)
        
        pred_maps.append(p)
        a = p

    pred_maps = np.array(pred_maps).reshape(n_samples,h,w)

    return pred_maps[n_daily_samples:,:,:]



def test():
    np.random.seed(1234)
    maps = np.random.random((30,12,5,4))*100
    preds = DMD_prediction(maps)
   
    print(preds.shape)

if __name__ == '__main__':

    test()
